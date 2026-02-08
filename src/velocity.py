"""
Velocity & Momentum Analysis for HazardPay.

Tracks HOW FAST prices are moving, not just WHERE they are.
Key insight: A 10% drop over 2 hours is very different from 10% over 2 weeks.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VelocityAnalysis:
    """Price velocity and momentum data."""
    
    # Velocity (% change per hour, negative = falling)
    velocity_1h: float   # Last hour
    velocity_6h: float   # Last 6 hours  
    velocity_24h: float  # Last 24 hours
    
    # Acceleration (is velocity changing?)
    # Positive = slowing down (good if falling), Negative = speeding up (bad)
    acceleration: float
    
    # Momentum state
    state: str  # 'FREEFALL', 'FALLING', 'STABILIZING', 'STABLE', 'RISING', 'SURGING'
    
    # Confidence (how much data we have)
    data_points: int
    hours_of_data: float
    
    # Summary
    description: str
    is_safe_to_buy: bool


def calculate_velocity(prices: List[Dict], current_price: int = None) -> Optional[VelocityAnalysis]:
    """
    Calculate price velocity from price history.
    
    Args:
        prices: List of {'price': int, 'recorded_at'/'timestamp': datetime} ordered newest first
        current_price: Current price (optional, uses first in list if not provided)
    
    Returns:
        VelocityAnalysis with momentum data
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
    
    # Find prices at different time windows
    # Store (price, actual_age_hours) for the closest data point to each target window
    price_1h_ago = None
    price_6h_ago = None
    price_24h_ago = None
    price_2h_ago = None  # For acceleration
    price_4h_ago = None  # For acceleration
    
    # Also track the best match for 1h (closest to 1.0h regardless of min threshold)
    best_1h_match = None
    best_1h_diff = float('inf')
    
    for p in prices:
        ts = p[ts_field]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        
        age_hours = (now - ts).total_seconds() / 3600
        
        # Track best match for 1h window (anything between 0.5h and 2h)
        if 0.5 <= age_hours <= 2.0:
            diff = abs(age_hours - 1.0)
            if diff < best_1h_diff:
                best_1h_diff = diff
                best_1h_match = (p['price'], age_hours)
        
        # Find closest price to each window (using relaxed thresholds)
        if price_1h_ago is None and age_hours >= 0.5:
            price_1h_ago = (p['price'], age_hours)
        if price_2h_ago is None and age_hours >= 1.5:
            price_2h_ago = (p['price'], age_hours)
        if price_4h_ago is None and age_hours >= 3.0:
            price_4h_ago = (p['price'], age_hours)
        if price_6h_ago is None and age_hours >= 5.0:
            price_6h_ago = (p['price'], age_hours)
        if price_24h_ago is None and age_hours >= 20:
            price_24h_ago = (p['price'], age_hours)
    
    # Use best 1h match if we found one, otherwise fall back to threshold match
    if best_1h_match:
        price_1h_ago = best_1h_match
    
    # Calculate velocities (% per hour)
    def calc_velocity(old_data: Tuple[int, float], current: int) -> float:
        if not old_data:
            return 0
        old_price, hours = old_data
        if old_price == 0 or hours == 0:
            return 0
        total_change_pct = ((current - old_price) / old_price) * 100
        return total_change_pct / hours  # % per hour
    
    v_1h = calc_velocity(price_1h_ago, current) if price_1h_ago else 0
    v_6h = calc_velocity(price_6h_ago, current) if price_6h_ago else v_1h
    v_24h = calc_velocity(price_24h_ago, current) if price_24h_ago else v_6h
    
    # Calculate acceleration (change in velocity)
    # Compare recent velocity (last 2h) to older velocity (2-4h ago)
    acceleration = 0
    if price_2h_ago and price_4h_ago:
        recent_velocity = calc_velocity(price_2h_ago, current)
        older_velocity = calc_velocity(price_4h_ago, price_2h_ago[0])
        acceleration = recent_velocity - older_velocity  # Positive = velocity increasing (less negative = slowing)
    
    # Determine momentum state
    state = "STABLE"
    description = "Price stable"
    is_safe = True
    
    # Check for freefall (rapid sustained drop)
    if v_1h < -2 and v_6h < -1:
        state = "FREEFALL"
        description = f"🚨 FREEFALL: Dropping {abs(v_1h):.1f}%/hour!"
        is_safe = False
    elif v_1h < -0.5 and v_6h < -0.3:
        # Is it slowing down?
        if acceleration > 0.3:
            state = "STABILIZING"
            description = f"📉 Falling but slowing ({v_1h:.1f}%/h, was faster)"
            is_safe = False  # Still wait for confirmation
        else:
            state = "FALLING"
            description = f"📉 Falling {abs(v_1h):.1f}%/hour"
            is_safe = False
    elif v_1h > 0.5 and v_6h > 0.3:
        if v_1h > 2:
            state = "SURGING"
            description = f"📈 SURGING: Up {v_1h:.1f}%/hour!"
            is_safe = True  # But might have missed the bottom
        else:
            state = "RISING"
            description = f"📈 Rising {v_1h:.1f}%/hour"
            is_safe = True
    elif abs(v_1h) < 0.3 and abs(v_6h) < 0.2:
        state = "STABLE"
        description = f"➖ Stable (±{abs(v_1h):.1f}%/h)"
        is_safe = True
    else:
        state = "CHOPPY"
        description = f"↔️ Choppy (1h: {v_1h:+.1f}%, 6h: {v_6h:+.1f}%)"
        is_safe = abs(v_1h) < 1  # Safe if not volatile
    
    # Calculate data quality
    oldest = prices[-1][ts_field]
    if isinstance(oldest, str):
        oldest = datetime.fromisoformat(oldest)
    hours_of_data = (now - oldest).total_seconds() / 3600
    
    return VelocityAnalysis(
        velocity_1h=v_1h,
        velocity_6h=v_6h,
        velocity_24h=v_24h,
        acceleration=acceleration,
        state=state,
        data_points=len(prices),
        hours_of_data=hours_of_data,
        description=description,
        is_safe_to_buy=is_safe
    )


def check_stabilization(prices: List[Dict], min_hours: float = 4.0, max_variance_pct: float = 3.0) -> Tuple[bool, str]:
    """
    Check if price has truly stabilized (not just a brief pause).
    
    Requirements for stabilization:
    1. At least min_hours of data
    2. Price variance within max_variance_pct
    3. No new lows in the last hour (higher lows pattern)
    
    Args:
        prices: List of {'price': int, 'recorded_at'/'timestamp': datetime} ordered newest first
        min_hours: Minimum hours of stability required
        max_variance_pct: Maximum price variance allowed (%)
    
    Returns:
        (is_stabilized, reason)
    """
    if not prices or len(prices) < 5:
        return False, "Insufficient data"
    
    # Support both field names
    ts_field = 'recorded_at' if 'recorded_at' in prices[0] else 'timestamp'
    if ts_field not in prices[0]:
        return False, "Missing timestamp data"
    
    now = datetime.now()
    
    # Get prices within our window
    window_prices = []
    for p in prices:
        ts = p[ts_field]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        
        age_hours = (now - ts).total_seconds() / 3600
        if age_hours <= min_hours:
            window_prices.append({'price': p['price'], 'age_hours': age_hours})
    
    if len(window_prices) < 4:
        return False, f"Only {len(window_prices)} data points in {min_hours}h window"
    
    # Check variance
    prices_only = [p['price'] for p in window_prices]
    min_price = min(prices_only)
    max_price = max(prices_only)
    
    if min_price == 0:
        return False, "Invalid price data"
    
    variance_pct = ((max_price - min_price) / min_price) * 100
    
    if variance_pct > max_variance_pct:
        return False, f"Too volatile: {variance_pct:.1f}% variance in {min_hours}h"
    
    # Check for higher lows pattern (no new lows recently)
    # Split into older half and newer half
    mid = len(window_prices) // 2
    older_prices = window_prices[mid:]
    newer_prices = window_prices[:mid]
    
    older_low = min(p['price'] for p in older_prices)
    newer_low = min(p['price'] for p in newer_prices)
    
    if newer_low < older_low * 0.98:  # New low is more than 2% lower
        return False, "Still making new lows"
    
    # Check last hour specifically
    last_hour = [p['price'] for p in window_prices if p['age_hours'] <= 1.0]
    if last_hour:
        last_hour_low = min(last_hour)
        overall_low = min_price
        if last_hour_low <= overall_low:
            return False, "Made new low in last hour"
    
    return True, f"Stable for {min_hours}h ({variance_pct:.1f}% variance, higher lows)"
