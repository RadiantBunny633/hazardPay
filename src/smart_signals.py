"""
Smart Trading Signals for HazardPay.
Context-aware buy/sell scoring based on FUT market dynamics.

V3: Enhanced with advanced velocity, deceleration detection, support levels,
    confidence scoring, and proper "when to buy falling assets" methodology.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .database import get_db, Database
from .scraper import FutbinScraper
from .velocity_v2 import calculate_velocity_v2, check_stabilization_v2, VelocityAnalysisV2

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """A trading signal with context."""
    player_id: str
    player_name: str
    signal_type: str  # 'STRONG_BUY', 'BUY', 'HOLD', 'WAIT', 'AVOID'
    score: int  # 0-100, higher = stronger signal
    reasons: List[str]
    warnings: List[str]
    current_price: int
    recommendation: str
    velocity: Optional[VelocityAnalysisV2] = None
    confidence: str = "MEDIUM"  # HIGH, MEDIUM, LOW


class SmartSignals:
    """
    Generates context-aware trading signals.
    
    V3.1 Improvements:
    - Velocity persistence (2h+ sustained direction required)
    - Deceleration detection (falling but slowing = potential bottom)
    - Higher lows pattern detection
    - Support level analysis
    - Confidence scoring based on data quality
    - Time since low tracking
    - Trend persistence (consecutive days in direction)
    - STATE HYSTERESIS: Require 2 consecutive readings to change state
    - STICKY READY: Once READY, stay for 2h unless price drops >3%
    """
    
    def __init__(self, db: Database = None, platform: str = 'ps'):
        self.db = db or get_db()
        self.platform = platform
    
    def _get_player_state(self, player_id: str) -> Optional[Dict]:
        """Get stored state for a player (for hysteresis)."""
        try:
            return self.db.db.player_states.find_one({'player_id': player_id, 'platform': self.platform})
        except:
            return None
    
    def _save_player_state(self, player_id: str, state: str, readiness: str, score: int, price: int):
        """Save current state for hysteresis tracking."""
        try:
            self.db.db.player_states.update_one(
                {'player_id': player_id, 'platform': self.platform},
                {'$set': {
                    'player_id': player_id,
                    'platform': self.platform,
                    'state': state,
                    'readiness': readiness,
                    'score': score,
                    'price': price,
                    'updated_at': datetime.now()
                }},
                upsert=True
            )
        except Exception as e:
            logger.debug(f"Could not save player state: {e}")
    
    def _apply_hysteresis(self, player_id: str, new_state: str, new_readiness: str, 
                          new_score: int, current_price: int, velocity) -> Tuple[str, str, int]:
        """
        Apply hysteresis to prevent twitchy state changes.
        
        Rules:
        1. STICKY READY: If was READY within 2h and price hasn't dropped >3%, stay READY
        2. STATE CHANGE: Require new state to be better by 10+ points to upgrade, 
           or worse by 15+ points to downgrade (asymmetric - harder to lose READY)
        """
        prev_state = self._get_player_state(player_id)
        
        if not prev_state:
            # First time seeing this player, use new values
            return new_state, new_readiness, new_score
        
        prev_readiness = prev_state.get('readiness', 'WAIT')
        prev_score = prev_state.get('score', 50)
        prev_price = prev_state.get('price', current_price)
        prev_time = prev_state.get('updated_at', datetime.now())
        
        hours_since_update = (datetime.now() - prev_time).total_seconds() / 3600
        price_change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
        
        # === STICKY READY: Once READY, stay for 2h unless price drops >3% ===
        if prev_readiness == "READY":
            if hours_since_update < 2.0 and price_change_pct > -3.0:
                # Keep READY - hasn't been long enough and price is okay
                if new_readiness != "READY":
                    logger.debug(f"Keeping {player_id} READY (sticky: {hours_since_update:.1f}h, price {price_change_pct:+.1f}%)")
                    # Use max of previous and new score to prevent artificial drops
                    return prev_state.get('state', new_state), "READY", max(prev_score - 5, new_score)
        
        # === HYSTERESIS: Require significant change to switch ===
        score_diff = new_score - prev_score
        
        # Upgrading (WAIT→ALMOST→READY): need 10+ point improvement
        readiness_levels = {"AVOID": 0, "WAIT": 1, "ALMOST": 2, "READY": 3}
        new_level = readiness_levels.get(new_readiness, 1)
        prev_level = readiness_levels.get(prev_readiness, 1)
        
        if new_level > prev_level:
            # Upgrading - need 10+ point improvement
            if score_diff < 10:
                logger.debug(f"Blocking upgrade {prev_readiness}→{new_readiness} (only +{score_diff} points)")
                return prev_state.get('state', new_state), prev_readiness, prev_score
        elif new_level < prev_level:
            # Downgrading - need 15+ point drop (harder to lose READY)
            if score_diff > -15:
                logger.debug(f"Blocking downgrade {prev_readiness}→{new_readiness} (only {score_diff} points)")
                return prev_state.get('state', new_state), prev_readiness, prev_score
        
        # Change is significant enough, allow it
        return new_state, new_readiness, new_score

    def _calculate_timing_score(self, velocity: Optional[VelocityAnalysisV2],
                                stabilization_result: tuple) -> Tuple[int, List[str], List[str]]:
        """
        Unified timing score that collapses velocity readiness, stabilization,
        deceleration, higher-lows, and support bounces into a single score.

        This fixes double-counting: velocity V2 already examines these sub-signals
        to compute buy_readiness. The old code then independently awarded +10/+10/+15
        more points for the same observations. Now readiness is the primary signal
        with small cross-confirmation bonuses.

        Returns:
            (score, reasons, warnings) where score is clamped to [-30, +30]
        """
        score = 0
        reasons = []
        warnings = []

        is_stable, stability_reason, stable_hours = stabilization_result

        if not velocity:
            return 0, [], ["⚠ No velocity data"]

        # === PRIMARY: Buy readiness (already integrates sub-signals) ===
        if velocity.buy_readiness == "READY":
            score = 22
            reasons.append(f"✓ {velocity.description}")
            reasons.append(f"✓ {velocity.buy_readiness_reason}")
        elif velocity.buy_readiness == "ALMOST":
            score = 10
            reasons.append(f"✓ {velocity.description}")
            warnings.append(f"⏳ {velocity.buy_readiness_reason}")
        elif velocity.buy_readiness == "WAIT":
            score = -5
            warnings.append(f"⚠ {velocity.description}")
            warnings.append(f"   {velocity.buy_readiness_reason}")
        elif velocity.buy_readiness == "AVOID":
            score = -25
            warnings.append(f"🚨 {velocity.description}")
            warnings.append(f"   {velocity.buy_readiness_reason}")

        # === CROSS-CONFIRMATION BONUSES (small, avoid double-counting) ===

        # Stabilization bonus: +5 if stable for 4h+ AND readiness is READY/ALMOST
        if is_stable and stable_hours >= 4 and velocity.buy_readiness in ("READY", "ALMOST"):
            score += 5
            reasons.append(f"✓ Stable for {stable_hours:.0f}h (confirmed)")
        elif not is_stable and "new low" in stability_reason.lower():
            score -= 5
            warnings.append(f"✗ {stability_reason}")

        # Support bounce bonus: +3 if bounced 2+ times at support AND readiness is READY/ALMOST
        if (velocity.support_level and velocity.times_bounced_at_support >= 2
                and velocity.buy_readiness in ("READY", "ALMOST")):
            score += 3
            reasons.append(f"✓ Support at {velocity.support_level:,} ({velocity.times_bounced_at_support}x)")

        # Extended downtrend penalty: -3 for 3+ days down
        if velocity.days_in_trend < -3:
            score -= 3
            warnings.append(f"⚠ Downtrend for {abs(velocity.days_in_trend)} days")
        elif velocity.days_in_trend > 2:
            warnings.append(f"⚠ Already up for {velocity.days_in_trend} days")

        # Clamp to [-30, +30]
        score = max(-30, min(30, score))
        return score, reasons, warnings

    def _log_signal(self, player_id: str, direction: str, raw_score: int, final_score: int,
                    components: Dict, velocity: Optional[VelocityAnalysisV2],
                    market_state: str, signal_type: str, price: int):
        """Log signal score with component breakdown for diagnostics. Never raises."""
        try:
            self.db.log_signal({
                'player_id': player_id,
                'platform': self.platform,
                'direction': direction,
                'raw_score': raw_score,
                'final_score': final_score,
                'components': components,
                'velocity_state': velocity.state if velocity else None,
                'buy_readiness': velocity.buy_readiness if velocity else None,
                'market_state': market_state,
                'signal_type': signal_type,
                'price': price,
            })
        except Exception as e:
            logger.debug(f"Signal logging failed: {e}")

    def refresh_longterm_cache(self, players: List[Dict]):
        """Pre-warm the longterm cache for a list of players. This is the ONLY
        place that makes network requests for longterm data during scoring."""
        scraper = FutbinScraper(platform=self.platform)
        for p in players:
            try:
                scraper.get_longterm_daily_prices(
                    p['futbin_id'],
                    p.get('slug', p['name'].lower().replace(' ', '-')),
                    cache_only=False
                )
            except Exception as e:
                logger.debug(f"Cache warm failed for {p.get('name', '?')}: {e}")

    def get_buy_score(self, player_id: str) -> TradeSignal:
        """
        Calculate buy score for a player.
        
        Score 0-100:
        - 80-100: STRONG BUY - Multiple factors aligned
        - 60-79: BUY - Good opportunity
        - 40-59: HOLD - Wait for better entry
        - 0-39: AVOID - Bad timing
        
        V2: Uses velocity, dynamic market-based scoring, real stabilization detection.
        """
        player = self.db.get_player(player_id=player_id)
        if not player:
            return None
        
        latest = self.db.get_latest_price(player_id, platform=self.platform)
        history = self.db.get_price_history(player_id, platform=self.platform, days=7, limit=200)
        
        if not latest or len(history) < 2:
            return TradeSignal(
                player_id=player_id,
                player_name=player['name'],
                signal_type='WAIT',
                score=0,
                reasons=['Insufficient data'],
                warnings=['Need more price history'],
                current_price=latest['price'] if latest else 0,
                recommendation='Wait for more data before trading'
            )
        
        score = 40  # Start below neutral - need to EARN buy rating
        reasons = []
        warnings = []

        current_price = latest['price']

        # Track component scores for diagnostic logging
        market_score = 0
        timing_score = 0
        position_score = 0
        bounce_penalty = 0

        # === MARKET PULSE (±15 points) ===
        market_state = "UNKNOWN"

        from .market_pulse import get_pulse_analyzer
        try:
            pulse_analyzer = get_pulse_analyzer(platform=self.platform)
            pulse = pulse_analyzer.get_pulse()

            if pulse:
                market_state = pulse.status

                if pulse.status == "CRASHED":
                    market_score = 15
                    reasons.append(f"✓ MARKET CRASHED ({pulse.pct_at_lows:.0f}% at lows)")
                elif pulse.status == "CRASHING":
                    market_score = -15
                    warnings.append(f"🚨 MARKET CRASHING ({pulse.pct_trending_down:.0f}% falling)")
                elif pulse.status == "INFLATED":
                    market_score = -15
                    warnings.append(f"✗ MARKET INFLATED ({pulse.pct_at_highs:.0f}% at highs)")
                elif pulse.status == "RECOVERING":
                    market_score = 5
                    reasons.append(f"✓ Market recovering ({pulse.avg_position_in_range:.0f}%)")
        except Exception as e:
            logger.debug(f"Could not get market pulse: {e}")

        score += market_score

        # === UNIFIED TIMING SCORE (±30 points) ===
        # Collapses velocity readiness + stabilization + deceleration + higher-lows + support
        velocity = calculate_velocity_v2(history, current_price)
        stabilization_result = check_stabilization_v2(history, min_hours=6.0, max_variance_pct=5.0)

        timing_score, timing_reasons, timing_warnings = self._calculate_timing_score(
            velocity, stabilization_result
        )
        score += timing_score
        reasons.extend(timing_reasons)
        warnings.extend(timing_warnings)

        # === HISTORICAL POSITION (±15 points) + BOUNCE PENALTY (-20 to 0) ===
        # Uses cache_only=True — cache is pre-warmed by refresh_longterm_cache()
        try:
            scraper = FutbinScraper(platform=self.platform)
            longterm = scraper.get_longterm_daily_prices(
                player['futbin_id'],
                player.get('slug', player['name'].lower().replace(' ', '-')),
                cache_only=True
            )

            if longterm and longterm['data_points'] >= 30:
                recent_position = longterm.get('recent_position', longterm['position_in_range'])
                bounce_from_low = longterm.get('bounce_from_low', 0)
                recent_low = longterm.get('recent_low', longterm['all_time_low'])

                # Bounce penalty (already recovered = bad entry)
                if bounce_from_low >= 50:
                    bounce_penalty = -20
                    warnings.append(f"🚨 Already bounced {bounce_from_low:.0f}% off low!")
                    warnings.append(f"   Low: {recent_low:,} → Now: {current_price:,}")
                elif bounce_from_low >= 30:
                    bounce_penalty = -12
                    warnings.append(f"⚠ Up {bounce_from_low:.0f}% from recent low")
                elif bounce_from_low >= 15:
                    bounce_penalty = -5
                    warnings.append(f"⚠ Bounced {bounce_from_low:.0f}% already")

                # Position in recent range
                if recent_position >= 80:
                    position_score = -15
                    warnings.append(f"🚨 Near 30-day HIGH ({recent_position:.0f}%)")
                elif recent_position >= 60:
                    position_score = -8
                    warnings.append(f"⚠ Upper range ({recent_position:.0f}%)")
                elif recent_position <= 15:
                    position_score = 15
                    reasons.append(f"🔥 Near 30-day LOW! ({recent_position:.0f}%)")
                elif recent_position <= 30:
                    position_score = 8
                    reasons.append(f"✓ Lower range ({recent_position:.0f}%)")
                elif recent_position <= 45:
                    position_score = 3
                    reasons.append(f"✓ Below mid ({recent_position:.0f}%)")
        except Exception as e:
            logger.debug(f"Could not fetch long-term data: {e}")
            warnings.append("⚠ No historical range data")

        score += position_score + bounce_penalty

        # === DETERMINE SIGNAL TYPE ===
        raw_score = score
        score = max(0, min(100, score))

        confidence = velocity.confidence if velocity else "LOW"
        raw_readiness = velocity.buy_readiness if velocity else "WAIT"
        raw_state = velocity.state if velocity else "STABLE"

        # === APPLY HYSTERESIS ===
        smoothed_state, smoothed_readiness, smoothed_score = self._apply_hysteresis(
            player_id, raw_state, raw_readiness, score, current_price, velocity
        )
        score = smoothed_score
        self._save_player_state(player_id, smoothed_state, smoothed_readiness, score, current_price)

        # Determine signal type from smoothed score
        if score >= 75:
            signal_type = 'STRONG BUY'
            recommendation = f"Multiple factors aligned. Good entry at {current_price:,}"
        elif score >= 60:
            signal_type = 'BUY'
            recommendation = f"Good opportunity at {current_price:,}"
        elif score >= 45:
            signal_type = 'HOLD'
            recommendation = "Conditions okay but not ideal. Consider waiting."
        elif score >= 30:
            signal_type = 'WAIT'
            recommendation = "Poor timing. Wait for better conditions."
        else:
            signal_type = 'AVOID'
            recommendation = "Bad timing. Do not buy now."

        # === LOG SIGNAL ===
        self._log_signal(
            player_id=player_id, direction='BUY',
            raw_score=raw_score, final_score=score,
            components={
                'base': 40, 'market': market_score,
                'timing': timing_score, 'position': position_score,
                'bounce_penalty': bounce_penalty,
            },
            velocity=velocity, market_state=market_state,
            signal_type=signal_type, price=current_price,
        )

        return TradeSignal(
            player_id=player_id,
            player_name=player['name'],
            signal_type=signal_type,
            score=score,
            reasons=reasons,
            warnings=warnings,
            current_price=current_price,
            recommendation=recommendation,
            velocity=velocity,
            confidence=confidence
        )
    
    def get_sell_score(self, player_id: str, buy_price: int) -> TradeSignal:
        """
        Calculate sell score for a held position.

        Score budget:
          Base 50 + Profit ±25 + Velocity V2 ±20 + Market ±15 + Position ±15
          Total range: 0-100

        Args:
            player_id: Player to check
            buy_price: Price you paid
        """
        player = self.db.get_player(player_id=player_id)
        if not player:
            return None

        latest = self.db.get_latest_price(player_id, platform=self.platform)
        history = self.db.get_price_history(player_id, platform=self.platform, days=7, limit=100)

        if not latest:
            return None

        score = 50
        reasons = []
        warnings = []

        current_price = latest['price']

        # Track component scores for diagnostic logging
        profit_score = 0
        velocity_score = 0
        market_score = 0
        position_score = 0

        # Calculate profit (after 5% EA tax)
        sell_after_tax = int(current_price * 0.95)
        profit = sell_after_tax - buy_price
        profit_pct = (profit / buy_price * 100) if buy_price else 0

        # === PROFIT LEVEL (-20 to +25) ===
        if profit_pct >= 20:
            profit_score = 25
            reasons.append(f"✓ Excellent profit: {profit_pct:.1f}% ({profit:,} coins)")
        elif profit_pct >= 10:
            profit_score = 15
            reasons.append(f"✓ Good profit: {profit_pct:.1f}% ({profit:,} coins)")
        elif profit_pct >= 5:
            profit_score = 5
            reasons.append(f"✓ Modest profit: {profit_pct:.1f}% ({profit:,} coins)")
        elif profit_pct <= -10:
            profit_score = -20
            warnings.append(f"✗ Losing {abs(profit_pct):.1f}% - consider cutting loss or holding")
        elif profit_pct < 0:
            profit_score = -10
            warnings.append(f"⚠ Currently down {abs(profit_pct):.1f}%")

        score += profit_score

        # === VELOCITY V2 (-10 to +20) ===
        velocity = calculate_velocity_v2(history, current_price)

        if velocity:
            v2_sell_map = {
                "FREEFALL": (20, f"🚨 {velocity.description} - SELL NOW", True),
                "FALLING": (12, f"⚠ {velocity.description} - sell before worse", True),
                "DECELERATING": (8, f"⚠ {velocity.description} - still falling", True),
                "STABLE": (5, f"➖ {velocity.description} - fine to sell", True),
                "BOTTOMING": (-3, f"📈 {velocity.description} - may be recovering", False),
                "RISING": (-5, f"📈 {velocity.description} - price still going up", False),
                "SURGING": (-10, f"📈 {velocity.description} - could wait for peak", False),
                "CHOPPY": (0, f"↔ {velocity.description} - unpredictable", True),
            }
            v_score, v_msg, is_reason = v2_sell_map.get(
                velocity.state, (0, velocity.description, True)
            )
            velocity_score = v_score
            if is_reason:
                reasons.append(v_msg)
            else:
                warnings.append(v_msg)

        score += velocity_score

        # === MARKET PULSE (-15 to +15) ===
        market_state = "UNKNOWN"
        from .market_pulse import get_pulse_analyzer
        try:
            pulse = get_pulse_analyzer(platform=self.platform).get_pulse()
            if pulse:
                market_state = pulse.status
                if pulse.status == "CRASHING":
                    market_score = 15
                    reasons.append(f"🚨 Market crashing - exit positions!")
                elif pulse.status == "INFLATED":
                    market_score = 10
                    reasons.append("✓ Market inflated - good time to sell")
                elif pulse.status == "CRASHED":
                    market_score = -15
                    warnings.append("⚠ Market at lows - bad time to sell")
        except:
            pass

        score += market_score

        # === HISTORICAL POSITION (-15 to +15) ===
        try:
            scraper = FutbinScraper(platform=self.platform)
            longterm = scraper.get_longterm_daily_prices(
                player['futbin_id'],
                player.get('slug', player['name'].lower().replace(' ', '-')),
                cache_only=True
            )

            if longterm and longterm['data_points'] >= 30:
                position = longterm['position_in_range']

                if position >= 80:
                    position_score = 15
                    reasons.append(f"✓ Near all-time high ({position:.0f}%)")
                elif position >= 60:
                    position_score = 8
                    reasons.append(f"✓ Upper range ({position:.0f}%)")
                elif position <= 20:
                    position_score = -15
                    warnings.append(f"✗ Near floor ({position:.0f}%) - terrible time to sell")
        except:
            pass

        score += position_score

        # === DETERMINE SIGNAL TYPE ===
        raw_score = score
        score = max(0, min(100, score))

        if score >= 75:
            signal_type = 'STRONG SELL'
            recommendation = f"Take profit! Sell at {current_price:,} ({profit_pct:.1f}% profit)"
        elif score >= 60:
            signal_type = 'SELL'
            recommendation = f"Good time to sell at {current_price:,}"
        elif score >= 45:
            signal_type = 'HOLD'
            recommendation = "Could sell, timing not optimal"
        elif score >= 30:
            signal_type = 'WAIT'
            recommendation = "Wait for better exit"
        else:
            signal_type = 'HOLD'
            recommendation = "Bad timing. Hold or cut losses."

        # === LOG SIGNAL ===
        self._log_signal(
            player_id=player_id, direction='SELL',
            raw_score=raw_score, final_score=score,
            components={
                'base': 50, 'profit': profit_score,
                'velocity': velocity_score, 'market': market_score,
                'position': position_score,
            },
            velocity=velocity, market_state=market_state,
            signal_type=signal_type, price=current_price,
        )

        return TradeSignal(
            player_id=player_id,
            player_name=player['name'],
            signal_type=signal_type,
            score=score,
            reasons=reasons,
            warnings=warnings,
            current_price=current_price,
            recommendation=recommendation,
            velocity=velocity
        )
    
    def scan_buy_opportunities(self, min_score: int = 65) -> List[TradeSignal]:
        """Scan all tracked players for buy opportunities."""
        players = self.db.get_active_players()

        # Pre-warm longterm cache before scoring loop
        self.refresh_longterm_cache(players)

        opportunities = []
        for player in players:
            signal = self.get_buy_score(player['id'])
            if signal and signal.score >= min_score:
                opportunities.append(signal)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        return opportunities

    def scan_sell_opportunities(self, positions: List[Dict], min_score: int = 65) -> List[TradeSignal]:
        """Scan held positions for sell opportunities."""
        # Pre-warm longterm cache for all position players
        players_to_warm = []
        for pos in positions:
            player = self.db.get_player(player_id=pos['player_id'])
            if player:
                players_to_warm.append(player)
        if players_to_warm:
            self.refresh_longterm_cache(players_to_warm)

        opportunities = []
        for pos in positions:
            signal = self.get_sell_score(pos['player_id'], pos['buy_price'])
            if signal and signal.score >= min_score:
                signal.position_id = pos.get('id')
                signal.buy_price = pos['buy_price']
                signal.quantity = pos.get('quantity', 1)
                opportunities.append(signal)

        opportunities.sort(key=lambda x: x.score, reverse=True)
        return opportunities


def get_smart_signals(platform: str = 'ps') -> SmartSignals:
    """Get SmartSignals instance."""
    return SmartSignals(platform=platform)
