"""
Velocity & Momentum Analysis V2 for HazardPay.

V2 Improvements:
1. Velocity persistence - requires 2h+ sustained direction
2. Deceleration detection - falling slower = potential bottom
3. Higher lows detection - classic reversal pattern
4. Support level detection - historical price floors
5. Confidence scoring - how reliable is this analysis?
6. Time since low - when did the floor happen?
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VelocityAnalysisV2:
    """Enhanced price velocity and momentum data."""
    
    # Velocity (% change per hour, negative = falling)
    velocity_1h: float   # Last hour
    velocity_2h: float   # Last 2 hours (for persistence check)
    velocity_6h: float   # Last 6 hours  
    velocity_24h: float  # Last 24 hours
    
    # Acceleration (is velocity changing?)
    # Positive while falling = slowing down (good sign)
    # Negative while falling = speeding up (bad sign)
    acceleration: float
    
    # Deceleration analysis
    is_decelerating: bool  # Falling but slowing down
    deceleration_hours: float  # How long has it been slowing?
    
    # Momentum state
    state: str  # 'FREEFALL', 'FALLING', 'DECELERATING', 'BOTTOMING', 'STABLE', 'RISING', 'SURGING'
    
    # Pattern detection
    has_higher_lows: bool  # Classic reversal pattern
    support_level: Optional[int]  # Historical floor price
    times_bounced_at_support: int  # How many times has this level held?
    
    # Timing
    hours_since_low: float  # When was the recent low?
    days_in_trend: int  # Consecutive days in current direction
    
    # Confidence
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    confidence_score: int  # 0-100
    data_points: int
    hours_of_data: float
    
    # Summary
    description: str
    buy_readiness: str  # 'READY', 'ALMOST', 'WAIT', 'AVOID'
    buy_readiness_reason: str


def _get_timestamp(p: Dict, ts_field: str) -> datetime:
    """Extract timestamp from price record."""
    ts = p[ts_field]
    if isinstance(ts, str):
        return datetime.fromisoformat(ts)
    return ts


def _find_support_levels(prices: List[Dict], ts_field: str) -> Tuple[Optional[int], int]:
    """
    Find price support levels - prices where the asset bounced multiple times.
    
    Returns (support_price, times_bounced)
    """
    if len(prices) < 20:
        return None, 0
    
    # Get all prices
    price_values = [p['price'] for p in prices]
    min_price = min(price_values)
    max_price = max(price_values)
    
    if max_price == min_price:
        return None, 0
    
    # Create price buckets (round to 2% increments)
    bucket_size = max(1, int(min_price * 0.02))
    
    # Count how many times price touched near lows and bounced
    low_touches = {}
    
    for i in range(1, len(prices) - 1):
        price = prices[i]['price']
        prev_price = prices[i-1]['price']
        next_price = prices[i+1]['price']
        
        # Is this a local minimum? (price lower than neighbors)
        if price < prev_price and price < next_price:
            bucket = (price // bucket_size) * bucket_size
            low_touches[bucket] = low_touches.get(bucket, 0) + 1
    
    if not low_touches:
        return None, 0
    
    # Find the most common low point
    best_support = max(low_touches.items(), key=lambda x: x[1])
    return best_support[0], best_support[1]


def _detect_higher_lows(prices: List[Dict], ts_field: str, window_days: int = 7) -> bool:
    """
    Detect higher lows pattern - each successive dip doesn't go as low.
    
    This is a classic reversal indicator.
    """
    if len(prices) < 10:
        return False
    
    now = datetime.now()
    cutoff = now - timedelta(days=window_days)
    
    # Get prices in window
    window_prices = []
    for p in prices:
        ts = _get_timestamp(p, ts_field)
        if ts >= cutoff:
            window_prices.append({'price': p['price'], 'ts': ts})
    
    if len(window_prices) < 5:
        return False
    
    # Find local minima
    lows = []
    for i in range(1, len(window_prices) - 1):
        if (window_prices[i]['price'] < window_prices[i-1]['price'] and 
            window_prices[i]['price'] < window_prices[i+1]['price']):
            lows.append(window_prices[i])
    
    if len(lows) < 2:
        return False
    
    # Check if lows are increasing (higher lows)
    # Compare first half lows to second half lows
    mid = len(lows) // 2
    early_lows = [l['price'] for l in lows[:mid]]
    recent_lows = [l['price'] for l in lows[mid:]]
    
    if not early_lows or not recent_lows:
        return False
    
    avg_early = sum(early_lows) / len(early_lows)
    avg_recent = sum(recent_lows) / len(recent_lows)
    
    # Recent lows should be at least 2% higher than early lows
    return avg_recent > avg_early * 1.02


def _calculate_trend_days(prices: List[Dict], ts_field: str) -> int:
    """
    Calculate how many consecutive days the price has been trending in current direction.
    
    Returns positive for uptrend days, negative for downtrend days.
    """
    if len(prices) < 2:
        return 0
    
    # Group prices by day
    daily_prices = {}
    for p in prices:
        ts = _get_timestamp(p, ts_field)
        day_key = ts.strftime('%Y-%m-%d')
        if day_key not in daily_prices:
            daily_prices[day_key] = []
        daily_prices[day_key].append(p['price'])
    
    # Get daily averages, sorted newest first
    daily_avgs = []
    for day_key in sorted(daily_prices.keys(), reverse=True):
        avg = sum(daily_prices[day_key]) / len(daily_prices[day_key])
        daily_avgs.append({'day': day_key, 'avg': avg})
    
    if len(daily_avgs) < 2:
        return 0
    
    # Determine current direction
    current_direction = 1 if daily_avgs[0]['avg'] > daily_avgs[1]['avg'] else -1
    
    # Count consecutive days in this direction
    streak = 0
    for i in range(len(daily_avgs) - 1):
        if daily_avgs[i]['avg'] > daily_avgs[i+1]['avg']:
            direction = 1
        elif daily_avgs[i]['avg'] < daily_avgs[i+1]['avg']:
            direction = -1
        else:
            direction = 0
        
        if direction == current_direction:
            streak += 1
        else:
            break
    
    return streak * current_direction


def _calculate_confidence(data_points: int, hours_of_data: float, price_variance: float) -> Tuple[str, int]:
    """
    Calculate confidence level based on data quality.
    
    Returns (confidence_label, confidence_score)
    """
    score = 50  # Base
    
    # More data points = higher confidence
    if data_points >= 100:
        score += 25
    elif data_points >= 50:
        score += 15
    elif data_points >= 20:
        score += 5
    else:
        score -= 15
    
    # More hours of history = higher confidence
    if hours_of_data >= 168:  # 7 days
        score += 15
    elif hours_of_data >= 48:  # 2 days
        score += 8
    elif hours_of_data >= 12:
        score += 3
    else:
        score -= 10
    
    # Lower variance = higher confidence (more predictable)
    if price_variance < 5:
        score += 10
    elif price_variance < 10:
        score += 5
    elif price_variance > 30:
        score -= 10
    
    score = max(0, min(100, score))
    
    if score >= 75:
        return 'HIGH', score
    elif score >= 50:
        return 'MEDIUM', score
    else:
        return 'LOW', score


def calculate_velocity_v2(prices: List[Dict], current_price: int = None) -> Optional[VelocityAnalysisV2]:
    """
    Enhanced velocity calculation with persistence, deceleration, and pattern detection.
    
    Args:
        prices: List of {'price': int, 'recorded_at'/'timestamp': datetime} ordered newest first
        current_price: Current price (optional, uses first in list if not provided)
    
    Returns:
        VelocityAnalysisV2 with comprehensive momentum data
    """
    if not prices or len(prices) < 3:
        return None
    
    # Support both field names
    ts_field = 'recorded_at' if 'recorded_at' in prices[0] else 'timestamp'
    if ts_field not in prices[0]:
        logger.warning("Price history missing timestamps, cannot calculate velocity")
        return None
    
    now = datetime.now()
    current = current_price or prices[0]['price']
    
    # ===== FIND PRICES AT DIFFERENT TIME WINDOWS =====
    price_windows = {}  # hour -> (price, actual_hours)
    target_hours = [1, 2, 4, 6, 12, 24, 48]
    
    for p in prices:
        ts = _get_timestamp(p, ts_field)
        age_hours = (now - ts).total_seconds() / 3600
        
        for target in target_hours:
            window_key = f"{target}h"
            if window_key not in price_windows:
                # Find closest match within 50% of target
                if target * 0.5 <= age_hours <= target * 1.5:
                    price_windows[window_key] = (p['price'], age_hours)
    
    # ===== CALCULATE VELOCITIES =====
    def calc_velocity(window_key: str) -> float:
        if window_key not in price_windows:
            return 0
        old_price, hours = price_windows[window_key]
        if old_price == 0 or hours == 0:
            return 0
        return ((current - old_price) / old_price * 100) / hours
    
    v_1h = calc_velocity('1h')
    v_2h = calc_velocity('2h')
    v_6h = calc_velocity('6h') or v_2h
    v_24h = calc_velocity('24h') or v_6h
    
    # ===== ACCELERATION (CHANGE IN VELOCITY) =====
    # Compare velocity from 0-2h ago vs 2-4h ago
    acceleration = 0
    if '2h' in price_windows and '4h' in price_windows:
        recent_v = calc_velocity('2h')
        
        # Calculate older velocity (from 4h price to 2h price)
        p_4h, h_4h = price_windows['4h']
        p_2h, h_2h = price_windows['2h']
        if p_4h > 0 and (h_4h - h_2h) > 0:
            older_v = ((p_2h - p_4h) / p_4h * 100) / (h_4h - h_2h)
            acceleration = recent_v - older_v
    
    # ===== DECELERATION DETECTION =====
    # Are we falling but slowing down?
    is_decelerating = False
    deceleration_hours = 0
    
    if v_2h < -0.3:  # Currently falling
        if acceleration > 0.2:  # But slowing down
            is_decelerating = True
            # Estimate how long we've been decelerating
            if v_1h > v_2h:  # Last hour was less negative than last 2h
                deceleration_hours = 1
            if v_2h > v_6h:  # Last 2h less negative than last 6h
                deceleration_hours = max(deceleration_hours, 2)
    
    # ===== FIND LOW AND TIME SINCE LOW =====
    all_prices = [p['price'] for p in prices]
    min_price = min(all_prices)
    min_idx = all_prices.index(min_price)
    min_ts = _get_timestamp(prices[min_idx], ts_field)
    hours_since_low = (now - min_ts).total_seconds() / 3600
    
    # ===== TREND DAYS =====
    days_in_trend = _calculate_trend_days(prices, ts_field)
    
    # ===== PATTERN DETECTION =====
    has_higher_lows = _detect_higher_lows(prices, ts_field)
    support_level, times_bounced = _find_support_levels(prices, ts_field)
    
    # ===== CALCULATE DATA QUALITY =====
    oldest = _get_timestamp(prices[-1], ts_field)
    hours_of_data = (now - oldest).total_seconds() / 3600
    
    price_variance = ((max(all_prices) - min(all_prices)) / min(all_prices) * 100) if min(all_prices) > 0 else 0
    confidence, confidence_score = _calculate_confidence(len(prices), hours_of_data, price_variance)
    
    # ===== DETERMINE MOMENTUM STATE =====
    # This is the key logic - more nuanced than V1
    
    state = "STABLE"
    description = "Price stable"
    buy_readiness = "WAIT"
    buy_reason = "Default"
    
    # Check velocity persistence (need 2h+ of consistent direction)
    sustained_falling = v_1h < -0.5 and v_2h < -0.3
    sustained_rising = v_1h > 0.5 and v_2h > 0.3
    
    if sustained_falling:
        if v_1h < -2 and v_2h < -1.5:
            # True freefall - sustained rapid drop
            state = "FREEFALL"
            description = f"🚨 FREEFALL: -{abs(v_1h):.1f}%/h sustained"
            buy_readiness = "AVOID"
            buy_reason = "Sustained rapid decline - wait for deceleration"
        elif is_decelerating and deceleration_hours >= 2:
            # Falling but clearly slowing - potential bottom
            state = "DECELERATING"
            description = f"📉 Falling but SLOWING ({v_1h:.1f}%/h, was {v_6h:.1f}%/h)"
            
            # Check for bottoming signals
            if has_higher_lows:
                state = "BOTTOMING"
                description = f"🔄 BOTTOMING: Higher lows + deceleration"
                buy_readiness = "ALMOST"
                buy_reason = "Strong reversal signals, wait for stability confirmation"
            elif hours_since_low > 12 and times_bounced >= 2:
                state = "BOTTOMING"
                description = f"🔄 BOTTOMING: Testing support level"
                buy_readiness = "ALMOST"
                buy_reason = f"Price near support ({support_level:,}), bounced {times_bounced}x"
            else:
                buy_readiness = "WAIT"
                buy_reason = "Slowing but not confirmed - need more signals"
        elif is_decelerating:
            # Just started slowing
            state = "DECELERATING"
            description = f"📉 Falling, starting to slow"
            buy_readiness = "WAIT"
            buy_reason = "Early deceleration - needs 2+ hours to confirm"
        else:
            state = "FALLING"
            description = f"📉 Falling {abs(v_1h):.1f}%/h"
            buy_readiness = "AVOID"
            buy_reason = "Active decline with no slowing"
    
    elif sustained_rising:
        if v_1h > 2:
            state = "SURGING"
            description = f"📈 SURGING: +{v_1h:.1f}%/h"
            buy_readiness = "WAIT"
            buy_reason = "Already surging - likely missed the bottom"
        else:
            state = "RISING"
            description = f"📈 Rising {v_1h:.1f}%/h"
            buy_readiness = "WAIT"
            buy_reason = "Price rising - wait for pullback"
    
    elif abs(v_1h) < 0.3 and abs(v_2h) < 0.2:
        state = "STABLE"
        description = f"➖ Stable (±{abs(v_1h):.1f}%/h)"
        
        # Stable is good - now check other factors
        if hours_since_low <= 48 and has_higher_lows:
            buy_readiness = "READY"
            buy_reason = "Stable after recent low with higher lows pattern"
        elif hours_since_low <= 24:
            buy_readiness = "READY"
            buy_reason = "Stable near recent low - good entry"
        elif hours_since_low <= 72:
            buy_readiness = "ALMOST"
            buy_reason = "Stable but low was 2-3 days ago"
        else:
            buy_readiness = "WAIT"
            buy_reason = "Stable but no recent low - not a dip buy"
    
    else:
        state = "CHOPPY"
        description = f"↔️ Choppy ({v_1h:+.1f}%/h)"
        buy_readiness = "WAIT"
        buy_reason = "Unpredictable movement"
    
    return VelocityAnalysisV2(
        velocity_1h=round(v_1h, 2),
        velocity_2h=round(v_2h, 2),
        velocity_6h=round(v_6h, 2),
        velocity_24h=round(v_24h, 2),
        acceleration=round(acceleration, 2),
        is_decelerating=is_decelerating,
        deceleration_hours=deceleration_hours,
        state=state,
        has_higher_lows=has_higher_lows,
        support_level=support_level,
        times_bounced_at_support=times_bounced,
        hours_since_low=round(hours_since_low, 1),
        days_in_trend=days_in_trend,
        confidence=confidence,
        confidence_score=confidence_score,
        data_points=len(prices),
        hours_of_data=round(hours_of_data, 1),
        description=description,
        buy_readiness=buy_readiness,
        buy_readiness_reason=buy_reason
    )


def check_stabilization_v2(prices: List[Dict], min_hours: float = 6.0, max_variance_pct: float = 5.0) -> Tuple[bool, str, float]:
    """
    Enhanced stabilization check.
    
    V2 improvements:
    - Longer window (6h default vs 4h)
    - Returns stabilization duration
    - Checks for consolidation pattern (shrinking volatility)
    
    Returns:
        (is_stabilized, reason, hours_stable)
    """
    if not prices or len(prices) < 5:
        return False, "Insufficient data", 0
    
    ts_field = 'recorded_at' if 'recorded_at' in prices[0] else 'timestamp'
    if ts_field not in prices[0]:
        return False, "Missing timestamp data", 0
    
    now = datetime.now()
    
    # Get prices within window
    window_prices = []
    for p in prices:
        ts = _get_timestamp(p, ts_field)
        age_hours = (now - ts).total_seconds() / 3600
        if age_hours <= min_hours:
            window_prices.append({'price': p['price'], 'age_hours': age_hours, 'ts': ts})
    
    if len(window_prices) < 5:
        return False, f"Only {len(window_prices)} points in {min_hours}h window", 0
    
    # Check variance
    prices_only = [p['price'] for p in window_prices]
    min_price = min(prices_only)
    max_price = max(prices_only)
    
    if min_price == 0:
        return False, "Invalid price data", 0
    
    variance_pct = ((max_price - min_price) / min_price) * 100
    
    if variance_pct > max_variance_pct:
        return False, f"Volatile: {variance_pct:.1f}% variance", 0
    
    # Check for higher lows in window (consolidating upward)
    mid = len(window_prices) // 2
    older_half = window_prices[mid:]
    newer_half = window_prices[:mid]
    
    older_low = min(p['price'] for p in older_half)
    newer_low = min(p['price'] for p in newer_half)
    
    if newer_low < older_low * 0.98:  # New low is >2% lower
        return False, "Still making new lows", 0
    
    # Find how long we've been stable
    # Look back until variance exceeds threshold
    stable_hours = 0
    for h in range(1, int(min_hours) + 1):
        h_prices = [p['price'] for p in window_prices if p['age_hours'] <= h]
        if len(h_prices) >= 2:
            h_variance = ((max(h_prices) - min(h_prices)) / min(h_prices)) * 100
            if h_variance <= max_variance_pct:
                stable_hours = h
    
    consolidating = newer_low > older_low * 1.01  # Higher lows
    
    if consolidating:
        return True, f"Consolidating {stable_hours}h (higher lows)", stable_hours
    else:
        return True, f"Stable {stable_hours}h ({variance_pct:.1f}% var)", stable_hours
