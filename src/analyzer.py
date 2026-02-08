"""
Investment Analyzer Module for HazardPay.
Identifies investment opportunities based on price trends and patterns.
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from .database import get_db, Database

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Types of investment signals."""
    PRICE_DROP = "price_drop"           # Significant price decrease
    PRICE_SPIKE = "price_spike"         # Significant price increase
    MOMENTUM_UP = "momentum_up"         # Trending upward
    MOMENTUM_DOWN = "momentum_down"     # Trending downward
    AT_FLOOR = "at_floor"              # At or near price range minimum
    HIGH_VOLATILITY = "high_volatility" # High price variance
    WATCHLIST_TARGET = "watchlist_target"  # Hit watchlist target price
    WL_BUY_WINDOW = "wl_buy_window"     # Weekend League buy window (Mon-Tue)
    WL_SELL_WINDOW = "wl_sell_window"   # Weekend League sell window (Thu-Fri)
    CONTENT_DROP = "content_drop"       # Near 6pm UK content time


@dataclass
class InvestmentSignal:
    """Container for an investment signal."""
    player_id: int
    player_name: str
    futbin_id: int
    signal_type: SignalType
    current_price: int
    message: str
    severity: str  # 'low', 'medium', 'high'
    data: Dict  # Additional signal-specific data
    created_at: datetime


class InvestmentAnalyzer:
    """Analyzes price data to identify investment opportunities."""
    
    def __init__(self, db: Database = None, platform: str = 'ps'):
        self.db = db or get_db()
        self.platform = platform
        
        # Configurable thresholds
        self.price_drop_threshold = 10.0  # Percent drop to trigger alert
        self.price_spike_threshold = 10.0  # Percent increase to trigger alert
        self.momentum_days = 3  # Days to check for momentum
        self.volatility_threshold = 15.0  # Volatility % to consider "high"
        self.floor_proximity_threshold = 5.0  # % above floor to trigger alert
    
    def run_full_analysis(self) -> List[InvestmentSignal]:
        """Run all analysis checks and return all signals."""
        signals = []
        
        # Run each analysis type
        signals.extend(self.find_price_drops())
        signals.extend(self.find_price_spikes())
        signals.extend(self.find_momentum_players())
        signals.extend(self.find_floor_prices())
        signals.extend(self.find_high_volatility())
        signals.extend(self.check_watchlist_targets())
        
        # FUT-specific signals
        signals.extend(self.check_weekend_league_cycle())
        signals.extend(self.check_content_drop_window())
        
        # Sort by severity (high first)
        severity_order = {'high': 0, 'medium': 1, 'low': 2}
        signals.sort(key=lambda s: (severity_order.get(s.severity, 3), s.created_at))
        
        return signals
    
    def find_price_drops(self, threshold: float = None) -> List[InvestmentSignal]:
        """
        Find players whose price dropped significantly in the last 24 hours.
        These could be buying opportunities.
        """
        threshold = threshold or self.price_drop_threshold
        signals = []
        
        try:
            drops = self.db.get_price_drops(threshold_pct=threshold, platform=self.platform)
            
            for drop in drops:
                pct = abs(float(drop['pct_change']))
                
                # Determine severity
                if pct >= 20:
                    severity = 'high'
                elif pct >= 15:
                    severity = 'medium'
                else:
                    severity = 'low'
                
                signals.append(InvestmentSignal(
                    player_id=drop['id'],
                    player_name=drop['name'],
                    futbin_id=0,  # Not in view, would need join
                    signal_type=SignalType.PRICE_DROP,
                    current_price=drop['current_price'],
                    message=f"Price dropped {pct:.1f}% in 24h ({drop['previous_price']:,} → {drop['current_price']:,})",
                    severity=severity,
                    data={
                        'previous_price': drop['previous_price'],
                        'price_change': drop['price_change'],
                        'pct_change': pct
                    },
                    created_at=datetime.now()
                ))
        except Exception as e:
            logger.error(f"Error finding price drops: {e}")
        
        return signals
    
    def find_price_spikes(self, threshold: float = None) -> List[InvestmentSignal]:
        """
        Find players whose price increased significantly.
        Could indicate selling opportunity or FOMO danger.
        """
        threshold = threshold or self.price_spike_threshold
        signals = []
        
        try:
            spikes = self.db.get_price_spikes(threshold_pct=threshold, platform=self.platform)
            
            for spike in spikes:
                pct = float(spike['pct_change'])
                
                if pct >= 25:
                    severity = 'high'
                elif pct >= 15:
                    severity = 'medium'
                else:
                    severity = 'low'
                
                signals.append(InvestmentSignal(
                    player_id=spike['id'],
                    player_name=spike['name'],
                    futbin_id=0,
                    signal_type=SignalType.PRICE_SPIKE,
                    current_price=spike['current_price'],
                    message=f"Price spiked {pct:.1f}% in 24h ({spike['previous_price']:,} → {spike['current_price']:,})",
                    severity=severity,
                    data={
                        'previous_price': spike['previous_price'],
                        'price_change': spike['price_change'],
                        'pct_change': pct
                    },
                    created_at=datetime.now()
                ))
        except Exception as e:
            logger.error(f"Error finding price spikes: {e}")
        
        return signals
    
    def find_momentum_players(self, days: int = None) -> List[InvestmentSignal]:
        """
        Find players with consistent price momentum over N days.
        Upward momentum = potential investment, downward = wait to buy.
        """
        days = days or self.momentum_days
        signals = []
        
        try:
            players = self.db.get_active_players()
            
            for player in players:
                history = self.db.get_price_history(
                    player['id'], 
                    platform=self.platform, 
                    days=days + 1
                )
                
                if len(history) < days:
                    continue
                
                # Get daily prices (most recent first)
                daily_prices = [h['price'] for h in history[:days + 1]]
                
                if len(daily_prices) < 2:
                    continue
                
                # Check for consistent direction
                increases = sum(1 for i in range(len(daily_prices) - 1) 
                              if daily_prices[i] > daily_prices[i + 1])
                decreases = sum(1 for i in range(len(daily_prices) - 1) 
                              if daily_prices[i] < daily_prices[i + 1])
                
                total_change = daily_prices[0] - daily_prices[-1]
                pct_change = (total_change / daily_prices[-1]) * 100 if daily_prices[-1] else 0
                
                # Strong upward momentum
                if increases >= days - 1 and pct_change > 5:
                    signals.append(InvestmentSignal(
                        player_id=player['id'],
                        player_name=player['name'],
                        futbin_id=player['futbin_id'],
                        signal_type=SignalType.MOMENTUM_UP,
                        current_price=daily_prices[0],
                        message=f"Trending up {days} days: +{pct_change:.1f}% ({daily_prices[-1]:,} → {daily_prices[0]:,})",
                        severity='medium',
                        data={
                            'days': days,
                            'start_price': daily_prices[-1],
                            'pct_change': pct_change,
                            'daily_prices': daily_prices
                        },
                        created_at=datetime.now()
                    ))
                
                # Strong downward momentum
                elif decreases >= days - 1 and pct_change < -5:
                    signals.append(InvestmentSignal(
                        player_id=player['id'],
                        player_name=player['name'],
                        futbin_id=player['futbin_id'],
                        signal_type=SignalType.MOMENTUM_DOWN,
                        current_price=daily_prices[0],
                        message=f"Trending down {days} days: {pct_change:.1f}% ({daily_prices[-1]:,} → {daily_prices[0]:,})",
                        severity='low',
                        data={
                            'days': days,
                            'start_price': daily_prices[-1],
                            'pct_change': pct_change,
                            'daily_prices': daily_prices
                        },
                        created_at=datetime.now()
                    ))
        except Exception as e:
            logger.error(f"Error analyzing momentum: {e}")
        
        return signals
    
    def find_floor_prices(self, threshold_pct: float = None) -> List[InvestmentSignal]:
        """
        Find players at or near their price range floor.
        At floor = minimal downside risk.
        """
        threshold_pct = threshold_pct or self.floor_proximity_threshold
        signals = []
        
        try:
            players = self.db.get_active_players()
            
            for player in players:
                latest = self.db.get_latest_price(player['id'], platform=self.platform)
                
                if not latest or not latest.get('price_min'):
                    continue
                
                price = latest['price']
                floor = latest['price_min']
                
                if floor <= 0:
                    continue
                
                above_floor_pct = ((price - floor) / floor) * 100
                
                if above_floor_pct <= threshold_pct:
                    severity = 'high' if above_floor_pct <= 2 else 'medium'
                    
                    signals.append(InvestmentSignal(
                        player_id=player['id'],
                        player_name=player['name'],
                        futbin_id=player['futbin_id'],
                        signal_type=SignalType.AT_FLOOR,
                        current_price=price,
                        message=f"Near price floor! {above_floor_pct:.1f}% above minimum ({floor:,})",
                        severity=severity,
                        data={
                            'price_min': floor,
                            'price_max': latest.get('price_max'),
                            'above_floor_pct': above_floor_pct
                        },
                        created_at=datetime.now()
                    ))
        except Exception as e:
            logger.error(f"Error finding floor prices: {e}")
        
        return signals
    
    def find_high_volatility(self, days: int = 7, threshold: float = None) -> List[InvestmentSignal]:
        """
        Find players with high price volatility.
        High volatility = flip opportunities but also risk.
        """
        threshold = threshold or self.volatility_threshold
        signals = []
        
        try:
            volatility_data = self.db.get_volatility_scores(days=days, platform=self.platform)
            
            for v in volatility_data:
                vol_pct = float(v['volatility_pct']) if v['volatility_pct'] else 0
                
                if vol_pct >= threshold:
                    severity = 'high' if vol_pct >= 25 else 'medium'
                    
                    signals.append(InvestmentSignal(
                        player_id=v['id'],
                        player_name=v['name'],
                        futbin_id=v['futbin_id'],
                        signal_type=SignalType.HIGH_VOLATILITY,
                        current_price=int(v['avg_price']),
                        message=f"High volatility: {vol_pct:.1f}% variance over {days} days (avg: {int(v['avg_price']):,})",
                        severity=severity,
                        data={
                            'volatility_pct': vol_pct,
                            'avg_price': v['avg_price'],
                            'std_dev': v['std_dev'],
                            'data_points': v['data_points']
                        },
                        created_at=datetime.now()
                    ))
        except Exception as e:
            logger.error(f"Error analyzing volatility: {e}")
        
        return signals
    
    def check_watchlist_targets(self) -> List[InvestmentSignal]:
        """
        Check if any watchlist players hit target buy/sell prices.
        """
        signals = []
        
        try:
            watchlist = self.db.get_watchlist()
            
            for item in watchlist:
                current = item.get('current_price')
                if not current:
                    continue
                
                target_buy = item.get('target_buy_price')
                target_sell = item.get('target_sell_price')
                
                # Check buy target
                if target_buy and current <= target_buy:
                    signals.append(InvestmentSignal(
                        player_id=item['player_id'],
                        player_name=item['name'],
                        futbin_id=item['futbin_id'],
                        signal_type=SignalType.WATCHLIST_TARGET,
                        current_price=current,
                        message=f"HIT BUY TARGET! Current: {current:,} <= Target: {target_buy:,}",
                        severity='high',
                        data={
                            'target_type': 'buy',
                            'target_price': target_buy,
                            'notes': item.get('notes')
                        },
                        created_at=datetime.now()
                    ))
                
                # Check sell target
                if target_sell and current >= target_sell:
                    signals.append(InvestmentSignal(
                        player_id=item['player_id'],
                        player_name=item['name'],
                        futbin_id=item['futbin_id'],
                        signal_type=SignalType.WATCHLIST_TARGET,
                        current_price=current,
                        message=f"HIT SELL TARGET! Current: {current:,} >= Target: {target_sell:,}",
                        severity='high',
                        data={
                            'target_type': 'sell',
                            'target_price': target_sell,
                            'notes': item.get('notes')
                        },
                        created_at=datetime.now()
                    ))
        except Exception as e:
            logger.error(f"Error checking watchlist: {e}")
        
        return signals
    
    def save_signals_as_alerts(self, signals: List[InvestmentSignal]) -> int:
        """Save signals to the database as alerts."""
        count = 0
        for signal in signals:
            try:
                self.db.add_alert(
                    player_id=signal.player_id,
                    alert_type=signal.signal_type.value,
                    message=signal.message,
                    price_at_alert=signal.current_price
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to save alert: {e}")
        return count
    
    def get_player_analysis(self, player_id: int) -> Dict:
        """Get comprehensive analysis for a single player."""
        player = self.db.get_player(player_id=player_id)
        if not player:
            return {}
        
        history = self.db.get_price_history(player_id, platform=self.platform, days=30)
        latest = self.db.get_latest_price(player_id, platform=self.platform)
        
        if not history:
            return {'player': player, 'message': 'No price history available'}
        
        prices = [h['price'] for h in history]
        
        analysis = {
            'player': player,
            'current_price': latest['price'] if latest else None,
            'price_history_days': len(set(h['recorded_at'].date() for h in history)),
            'data_points': len(history),
            'price_range': {
                'min': min(prices),
                'max': max(prices),
                'avg': sum(prices) / len(prices)
            }
        }
        
        # Calculate trends
        if len(prices) >= 2:
            analysis['change_24h'] = {
                'absolute': prices[0] - prices[-1] if len(prices) > 1 else 0,
                'percent': ((prices[0] - prices[-1]) / prices[-1] * 100) if prices[-1] else 0
            }
        
        # Volatility
        if len(prices) >= 3:
            import statistics
            analysis['volatility'] = {
                'std_dev': statistics.stdev(prices),
                'coefficient': (statistics.stdev(prices) / statistics.mean(prices)) * 100
            }
        
        return analysis
    
    # ========== FUT-Specific Signals ==========
    
    def check_weekend_league_cycle(self) -> List[InvestmentSignal]:
        """
        Detect Weekend League trading cycle.
        
        FUT Market Weekly Pattern:
        - Monday-Tuesday: Post-WL sell-off → BUY WINDOW 🟢
        - Wednesday: Recovery begins
        - Thursday-Friday: WL prep, demand rises → SELL WINDOW 🔴
        - Saturday-Sunday: WL active, stable/high prices
        """
        signals = []
        now = datetime.now()
        day = now.weekday()  # 0=Monday, 6=Sunday
        hour = now.hour
        
        # Monday or Tuesday = Buy Window
        if day in [0, 1]:
            signals.append(InvestmentSignal(
                player_id=0,
                player_name="[MARKET WIDE]",
                futbin_id=0,
                signal_type=SignalType.WL_BUY_WINDOW,
                current_price=0,
                message="🟢 Weekend League BUY WINDOW - Post-WL sell-off, prices typically low",
                severity='high',
                data={
                    'day': ['Monday', 'Tuesday'][day],
                    'recommendation': 'Buy meta players now, sell Thu-Fri',
                    'cycle_phase': 'post_wl_dip'
                },
                created_at=now
            ))
        
        # Thursday or Friday (especially before 6pm content) = Sell Window
        elif day in [3, 4]:
            signals.append(InvestmentSignal(
                player_id=0,
                player_name="[MARKET WIDE]",
                futbin_id=0,
                signal_type=SignalType.WL_SELL_WINDOW,
                current_price=0,
                message="🔴 Weekend League SELL WINDOW - Pre-WL demand high, prices peak",
                severity='high',
                data={
                    'day': ['Thursday', 'Friday'][day - 3],
                    'recommendation': 'Sell meta players now, buy Mon-Tue',
                    'cycle_phase': 'pre_wl_peak'
                },
                created_at=now
            ))
        
        # Wednesday = Transition
        elif day == 2:
            signals.append(InvestmentSignal(
                player_id=0,
                player_name="[MARKET WIDE]",
                futbin_id=0,
                signal_type=SignalType.WL_BUY_WINDOW,
                current_price=0,
                message="🟡 Wednesday - Last chance to buy before prices rise Thu-Fri",
                severity='medium',
                data={
                    'day': 'Wednesday',
                    'recommendation': 'Final buy window before WL demand kicks in',
                    'cycle_phase': 'transition'
                },
                created_at=now
            ))
        
        return signals
    
    def check_content_drop_window(self) -> List[InvestmentSignal]:
        """
        Check if we're near the daily 6pm UK content drop.
        
        EA typically drops content at 6pm UK (18:00 GMT/BST).
        Prices can spike or crash depending on content.
        """
        signals = []
        now = datetime.now()
        
        # Rough check - 6pm UK is typically 1pm EST, 10am PST
        # We'll just check local time 5-7pm as a proxy
        hour = now.hour
        
        if 17 <= hour <= 19:
            signals.append(InvestmentSignal(
                player_id=0,
                player_name="[MARKET WIDE]",
                futbin_id=0,
                signal_type=SignalType.CONTENT_DROP,
                current_price=0,
                message="⚡ Content drop window - Expect volatility, new promos/SBCs may affect prices",
                severity='medium',
                data={
                    'local_hour': hour,
                    'recommendation': 'Watch for new SBCs, promos, TOTW. Prices may swing.',
                    'typical_content': ['New SBCs', 'Promo cards', 'TOTW release (Wed)', 'Flash SBCs']
                },
                created_at=now
            ))
        
        return signals
    
    def get_market_phase(self) -> Dict:
        """Get current market phase based on WL cycle."""
        now = datetime.now()
        day = now.weekday()
        
        phases = {
            0: {'phase': 'buy', 'name': 'Monday Dip', 'action': '🟢 BUY', 'desc': 'Post-WL sell-off'},
            1: {'phase': 'buy', 'name': 'Tuesday Dip', 'action': '🟢 BUY', 'desc': 'Continued low prices'},
            2: {'phase': 'transition', 'name': 'Wednesday', 'action': '🟡 HOLD/BUY', 'desc': 'Last buy chance'},
            3: {'phase': 'sell', 'name': 'Thursday Peak', 'action': '🔴 SELL', 'desc': 'WL prep begins'},
            4: {'phase': 'sell', 'name': 'Friday Peak', 'action': '🔴 SELL', 'desc': 'WL demand peaks'},
            5: {'phase': 'hold', 'name': 'Saturday WL', 'action': '⚪ HOLD', 'desc': 'WL active'},
            6: {'phase': 'hold', 'name': 'Sunday WL', 'action': '⚪ HOLD', 'desc': 'WL ending soon'},
        }
        
        return phases.get(day, phases[0])


def get_analyzer(platform: str = 'ps') -> InvestmentAnalyzer:
    """Get an InvestmentAnalyzer instance."""
    return InvestmentAnalyzer(platform=platform)
