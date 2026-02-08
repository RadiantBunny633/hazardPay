"""
Market Pulse - Real-time market health detection based on tracked players.

Instead of predicting crashes from a calendar, this DETECTS market conditions
by analyzing the actual behavior of tracked players:
- Are most players crashing?
- Are we at market-wide lows?
- Is the market inflated?
- What's the overall trend?

This uses your tracked players as a "market index" to understand conditions.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .database import get_db, Database
from .scraper import FutbinScraper

logger = logging.getLogger(__name__)


@dataclass
class CategoryPulse:
    """Pulse data for a specific player category."""
    name: str
    count: int
    avg_position: float  # 0-100%
    pct_at_lows: float  # % within 25% of all-time low
    pct_at_highs: float  # % within 75%+ of range
    pct_trending_down: float
    pct_trending_up: float
    status: str  # 'CRASHED', 'LOW', 'NORMAL', 'HIGH', 'INFLATED'
    
    @property
    def status_emoji(self) -> str:
        return {
            'CRASHED': '🟢',
            'LOW': '🟡',
            'NORMAL': '⚪',
            'HIGH': '🟠',
            'INFLATED': '🔴'
        }.get(self.status, '⚪')


@dataclass
class MarketPulse:
    """Current market health status."""
    
    # Overall status
    status: str  # 'CRASHED', 'CRASHING', 'STABLE', 'RECOVERING', 'INFLATED'
    health_score: int  # 0-100 (0 = crashed, 100 = peak)
    
    # Detailed metrics
    pct_at_lows: float  # % of players within 20% of all-time low
    pct_at_highs: float  # % of players within 20% of all-time high
    pct_trending_down: float  # % of players down in last 24h
    pct_trending_up: float  # % of players up in last 24h
    avg_position_in_range: float  # Average position (0-100%) across all players
    
    # Interpretation
    summary: str
    buy_sentiment: str  # 'GREAT', 'GOOD', 'NEUTRAL', 'RISKY', 'AVOID'
    sell_sentiment: str
    
    # Data
    players_analyzed: int
    timestamp: datetime
    
    # Fields with defaults must come last
    categories: Dict[str, CategoryPulse] = field(default_factory=dict)
    fodder_status: str = "Unknown"
    fodder_avg_position: float = 50


class MarketPulseAnalyzer:
    """
    Analyzes market health by looking at real player data.
    
    This is the "canary in the coal mine" approach:
    - Track diverse players (fodder, icons, TOTW, etc.)
    - If MOST are crashing, the market is crashing
    - If MOST are at lows, we're in a crash (BUY opportunity)
    - If MOST are at highs, market is inflated (SELL or wait)
    """
    
    def __init__(self, db: Database = None, platform: str = 'ps'):
        self.db = db or get_db()
        self.platform = platform
        self.scraper = FutbinScraper(platform=platform)
    
    def _categorize_player(self, player: dict, current_price: int, all_time_high: int) -> str:
        """Determine category, preferring stored card_type from enrichment."""
        # Use enriched card_type if available
        stored = player.get('card_type')
        if stored:
            category_map = {
                'ICON': 'Icons',
                'HERO': 'Heroes',
                'TOTY': 'TOTY',
                'TOTW': 'TOTW',
                'PROMO': 'TOTW',  # Treat promos like TOTW for market analysis
            }
            if stored in category_map:
                return category_map[stored]
            # GOLD_RARE, SILVER, BRONZE, OTHER fall through to fodder classification

        # Fallback: ID-based heuristics for un-enriched players
        futbin_id = player.get('futbin_id', 0)
        if 18699 <= futbin_id <= 21500 and all_time_high >= 200000:
            return 'Icons'
        if 18800 <= futbin_id <= 18900:
            return 'Heroes'
        if 21760 <= futbin_id <= 21780 and all_time_high >= 500000:
            return 'TOTY'
        if 20000 <= futbin_id <= 22500 and 10000 <= current_price <= 50000:
            return 'TOTW'

        # Fodder by price tier
        if current_price >= 20000:
            return '89+ Fodder'
        elif current_price >= 5000:
            return '87-88 Fodder'
        elif current_price >= 1000:
            return '86 Fodder'
        else:
            return '85 Fodder'
    
    def _calculate_category_pulse(self, stats: List[dict], name: str) -> CategoryPulse:
        """Calculate pulse metrics for a category."""
        if not stats:
            return CategoryPulse(
                name=name, count=0, avg_position=50,
                pct_at_lows=0, pct_at_highs=0,
                pct_trending_down=0, pct_trending_up=0,
                status='NORMAL'
            )
        
        positions = [s['position_in_range'] for s in stats]
        changes = [s['pct_change_24h'] for s in stats]
        
        avg_position = sum(positions) / len(positions)
        pct_at_lows = sum(1 for p in positions if p <= 25) / len(positions) * 100
        pct_at_highs = sum(1 for p in positions if p >= 75) / len(positions) * 100
        pct_trending_down = sum(1 for c in changes if c < -2) / len(changes) * 100
        pct_trending_up = sum(1 for c in changes if c > 2) / len(changes) * 100
        
        # Determine status
        if avg_position <= 20 or pct_at_lows >= 60:
            status = 'CRASHED'
        elif avg_position <= 35:
            status = 'LOW'
        elif avg_position >= 75 or pct_at_highs >= 50:
            status = 'INFLATED'
        elif avg_position >= 60:
            status = 'HIGH'
        else:
            status = 'NORMAL'
        
        return CategoryPulse(
            name=name,
            count=len(stats),
            avg_position=avg_position,
            pct_at_lows=pct_at_lows,
            pct_at_highs=pct_at_highs,
            pct_trending_down=pct_trending_down,
            pct_trending_up=pct_trending_up,
            status=status
        )
    
    def get_pulse(self, fetch_fresh: bool = False) -> Optional[MarketPulse]:
        """
        Analyze market health based on all tracked players.
        
        Args:
            fetch_fresh: If True, scrape fresh data from Futbin for each player.
                        If False, use cached long-term data (faster but may be stale).
        
        Returns:
            MarketPulse object with current market status
        """
        players = self.db.get_all_players()
        
        if len(players) < 3:
            logger.warning("Need at least 3 tracked players for market pulse")
            return None
        
        # Collect data for each player, organized by category
        all_stats = []
        category_stats: Dict[str, List[dict]] = {}
        
        for p in players:
            try:
                # Get long-term data
                longterm = self.scraper.get_longterm_daily_prices(
                    p['futbin_id'], 
                    p.get('slug', p['name'].lower().replace(' ', '-'))
                )
                
                if not longterm or longterm['data_points'] < 10:
                    continue
                
                # Get recent price changes from our DB
                history = self.db.get_price_history(p['id'], platform=self.platform, days=2, limit=50)
                
                # Calculate 24h change
                pct_change_24h = 0
                if len(history) >= 2:
                    current = history[0]['price']
                    older = history[-1]['price']
                    pct_change_24h = ((current - older) / older * 100) if older else 0
                
                stat = {
                    'name': p['name'],
                    'futbin_id': p['futbin_id'],
                    'position_in_range': longterm['position_in_range'],
                    'current': longterm['current'],
                    'all_time_low': longterm['all_time_low'],
                    'all_time_high': longterm['all_time_high'],
                    'pct_change_24h': pct_change_24h,
                    'volatility': longterm['volatility_pct']
                }
                
                all_stats.append(stat)
                
                # Categorize player
                category = self._categorize_player(p, longterm['current'], longterm['all_time_high'])
                if category not in category_stats:
                    category_stats[category] = []
                category_stats[category].append(stat)
                    
            except Exception as e:
                logger.warning(f"Could not analyze {p['name']}: {e}")
                continue
        
        if len(all_stats) < 3:
            logger.warning("Not enough valid player data for market pulse")
            return None
        
        # Calculate overall metrics
        positions = [s['position_in_range'] for s in all_stats]
        changes = [s['pct_change_24h'] for s in all_stats]
        
        avg_position = sum(positions) / len(positions)
        pct_at_lows = sum(1 for p in positions if p <= 25) / len(positions) * 100
        pct_at_highs = sum(1 for p in positions if p >= 75) / len(positions) * 100
        pct_trending_down = sum(1 for c in changes if c < -2) / len(changes) * 100
        pct_trending_up = sum(1 for c in changes if c > 2) / len(changes) * 100
        
        # Calculate category pulses
        categories = {}
        for cat_name, cat_stats in category_stats.items():
            categories[cat_name] = self._calculate_category_pulse(cat_stats, cat_name)
        
        # Get combined fodder pulse
        fodder_stats = []
        for cat_name in ['85 Fodder', '86 Fodder', '87-88 Fodder', '89+ Fodder']:
            if cat_name in category_stats:
                fodder_stats.extend(category_stats[cat_name])
        
        fodder_pulse = self._calculate_category_pulse(fodder_stats, 'All Fodder')
        fodder_status = fodder_pulse.status
        fodder_avg_position = fodder_pulse.avg_position
        
        # Determine overall status
        status, health_score, summary = self._determine_status(
            avg_position, pct_at_lows, pct_at_highs, 
            pct_trending_down, pct_trending_up, fodder_avg_position
        )
        
        # Determine sentiment
        buy_sentiment, sell_sentiment = self._determine_sentiment(
            status, avg_position, pct_at_lows, pct_trending_down
        )
        
        return MarketPulse(
            status=status,
            health_score=health_score,
            pct_at_lows=pct_at_lows,
            pct_at_highs=pct_at_highs,
            pct_trending_down=pct_trending_down,
            pct_trending_up=pct_trending_up,
            avg_position_in_range=avg_position,
            categories=categories,
            fodder_status=fodder_status,
            fodder_avg_position=fodder_avg_position,
            summary=summary,
            buy_sentiment=buy_sentiment,
            sell_sentiment=sell_sentiment,
            players_analyzed=len(all_stats),
            timestamp=datetime.now()
        )
    
    def _determine_status(
        self, 
        avg_position: float,
        pct_at_lows: float,
        pct_at_highs: float,
        pct_trending_down: float,
        pct_trending_up: float,
        fodder_position: float
    ) -> Tuple[str, int, str]:
        """Determine overall market status from metrics."""
        
        # CRASHED: Most players near their lows
        if pct_at_lows >= 50 or avg_position <= 25:
            status = "CRASHED"
            health_score = int(avg_position)
            summary = f"🟢 MARKET CRASHED - {pct_at_lows:.0f}% of players near all-time lows. BUY WINDOW!"
        
        # CRASHING: Active downtrend
        elif pct_trending_down >= 60 and avg_position > 30:
            status = "CRASHING"
            health_score = int(avg_position * 0.8)
            summary = f"🔻 MARKET CRASHING - {pct_trending_down:.0f}% trending down. Wait for floor."
        
        # INFLATED: Most players near highs
        elif pct_at_highs >= 40 or avg_position >= 70:
            status = "INFLATED"
            health_score = int(100 - (avg_position - 50))
            summary = f"🔴 MARKET INFLATED - {pct_at_highs:.0f}% near all-time highs. Risky to buy."
        
        # RECOVERING: Coming up from lows
        elif avg_position <= 40 and pct_trending_up >= 40:
            status = "RECOVERING"
            health_score = int(avg_position + 20)
            summary = f"📈 MARKET RECOVERING - {pct_trending_up:.0f}% trending up from lows."
        
        # STABLE: Normal conditions
        else:
            status = "STABLE"
            health_score = 50
            summary = f"➖ MARKET STABLE - Average position {avg_position:.0f}%. Normal conditions."
        
        return status, health_score, summary
    
    def _determine_sentiment(
        self,
        status: str,
        avg_position: float,
        pct_at_lows: float,
        pct_trending_down: float
    ) -> Tuple[str, str]:
        """Determine buy/sell sentiment."""
        
        if status == "CRASHED":
            buy_sentiment = "GREAT"
            sell_sentiment = "AVOID"
        elif status == "CRASHING":
            buy_sentiment = "RISKY"  # Catching falling knife
            sell_sentiment = "AVOID"
        elif status == "INFLATED":
            buy_sentiment = "AVOID"
            sell_sentiment = "GREAT"
        elif status == "RECOVERING":
            buy_sentiment = "GOOD"
            sell_sentiment = "NEUTRAL"
        else:
            buy_sentiment = "NEUTRAL"
            sell_sentiment = "NEUTRAL"
        
        return buy_sentiment, sell_sentiment


# Singleton
_pulse_analyzer = None

def get_pulse_analyzer(platform: str = 'ps') -> MarketPulseAnalyzer:
    """Get the market pulse analyzer singleton."""
    global _pulse_analyzer
    if _pulse_analyzer is None or _pulse_analyzer.platform != platform:
        _pulse_analyzer = MarketPulseAnalyzer(platform=platform)
    return _pulse_analyzer
