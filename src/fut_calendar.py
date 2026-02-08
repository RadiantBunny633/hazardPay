"""
FUT Calendar & Market Dynamics Module.
Based on comprehensive FIFA 23-FC 26 market research.
"""

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum


class MarketPhase(Enum):
    """Annual market cycle phases."""
    EARLY = "early"      # Sept-Oct: High prices, low supply
    MID = "mid"          # Nov-Feb: Gradual decline, major crashes
    LATE = "late"        # Mar-May: TOTS depreciation
    END = "end"          # June-Aug: Collapse to discard


class CrashEvent(Enum):
    """Major market crash events."""
    BLACK_FRIDAY = "black_friday"
    TOTY = "toty"
    TOTS = "tots"
    FUTTIES = "futties"


@dataclass
class PromoEvent:
    """Represents a promo/event in the FUT calendar."""
    name: str
    start_date: datetime
    end_date: datetime
    crash_severity: str  # 'minor', 'moderate', 'major', 'extreme'
    description: str
    trading_notes: str


# FC 26 Promo Calendar (2025-2026 Season)
FC26_CALENDAR = [
    PromoEvent(
        name="Cornerstones",
        start_date=datetime(2025, 9, 20),
        end_date=datetime(2025, 9, 27),
        crash_severity="minor",
        description="Launch promo",
        trading_notes="Early game, prices volatile but high"
    ),
    PromoEvent(
        name="Road to the Knockouts",
        start_date=datetime(2025, 10, 10),
        end_date=datetime(2025, 10, 24),
        crash_severity="minor",
        description="UCL/UEL promo",
        trading_notes="Meta UCL players spike"
    ),
    PromoEvent(
        name="Trailblazers",
        start_date=datetime(2025, 10, 25),
        end_date=datetime(2025, 11, 8),
        crash_severity="moderate",
        description="Position change promo",
        trading_notes="Pre-BF nervousness begins"
    ),
    PromoEvent(
        name="Centurions",
        start_date=datetime(2025, 11, 8),
        end_date=datetime(2025, 11, 22),
        crash_severity="moderate",
        description="100 stat boost promo",
        trading_notes="Sell before Black Friday"
    ),
    PromoEvent(
        name="Black Friday / Thunderstruck",
        start_date=datetime(2025, 11, 25),
        end_date=datetime(2025, 12, 2),
        crash_severity="major",
        description="Lightning rounds, flash SBCs",
        trading_notes="BUY Saturday during lightning rounds. 20-40% drops on 100k+ cards"
    ),
    PromoEvent(
        name="Winter Wildcards",
        start_date=datetime(2025, 12, 13),
        end_date=datetime(2026, 1, 3),
        crash_severity="moderate",
        description="Winter promo",
        trading_notes="Sell before TOTY panic (Jan 10)"
    ),
    PromoEvent(
        name="TOTY",
        start_date=datetime(2026, 1, 16),
        end_date=datetime(2026, 1, 30),
        crash_severity="extreme",
        description="Team of the Year - BIGGEST CRASH",
        trading_notes="Liquidate by Jan 10. Buy during full XI (Jan 22-30). Meta golds drop 30-50%"
    ),
    PromoEvent(
        name="Future Stars",
        start_date=datetime(2026, 2, 6),
        end_date=datetime(2026, 2, 20),
        crash_severity="minor",
        description="Young player promo",
        trading_notes="Post-TOTY recovery, good buying"
    ),
    PromoEvent(
        name="FUT Birthday",
        start_date=datetime(2026, 3, 20),
        end_date=datetime(2026, 4, 3),
        crash_severity="moderate",
        description="Anniversary promo",
        trading_notes="88-91 fodder spikes for Icon SBCs"
    ),
    PromoEvent(
        name="TOTS",
        start_date=datetime(2026, 4, 24),
        end_date=datetime(2026, 6, 5),
        crash_severity="extreme",
        description="Team of the Season - Sustained 6-week crash",
        trading_notes="Biggest sustained crash. Buy Mon/Tue of each league. Previous promos become worthless"
    ),
    PromoEvent(
        name="FUTTIES",
        start_date=datetime(2026, 7, 10),
        end_date=datetime(2026, 8, 14),
        crash_severity="major",
        description="End of cycle",
        trading_notes="Cards approach discard. Only trade for fun"
    ),
]


class FUTCalendar:
    """FUT market calendar and timing utilities."""
    
    def __init__(self):
        self.events = FC26_CALENDAR
    
    def get_current_phase(self) -> Dict:
        """Get the current annual market phase."""
        now = datetime.now()
        month = now.month
        
        if month in [9, 10]:
            return {
                'phase': MarketPhase.EARLY,
                'name': 'Early Cycle',
                'description': 'High prices, low supply. Base golds and ICONs at peak.',
                'strategy': 'SELL meta cards. Prices only go down from here.',
                'icon': '📈'
            }
        elif month in [11, 12, 1, 2]:
            return {
                'phase': MarketPhase.MID,
                'name': 'Mid Cycle',
                'description': 'Gradual decline with major crashes (BF, TOTY).',
                'strategy': 'Trade the crashes. Buy dips, sell recoveries.',
                'icon': '📊'
            }
        elif month in [3, 4, 5]:
            return {
                'phase': MarketPhase.LATE,
                'name': 'Late Cycle (TOTS)',
                'description': 'TOTS causes sustained depreciation.',
                'strategy': 'Only buy TOTS cards. Everything else loses value.',
                'icon': '📉'
            }
        else:  # 6, 7, 8
            return {
                'phase': MarketPhase.END,
                'name': 'End Cycle',
                'description': 'FUTTIES and pre-season. Market collapse.',
                'strategy': 'Minimal trading. Cards approach discard.',
                'icon': '💀'
            }
    
    def get_active_promo(self) -> Optional[PromoEvent]:
        """Get currently active promo if any."""
        now = datetime.now()
        for event in self.events:
            if event.start_date <= now <= event.end_date:
                return event
        return None
    
    def get_next_promo(self) -> Optional[PromoEvent]:
        """Get the next upcoming promo."""
        now = datetime.now()
        future = [e for e in self.events if e.start_date > now]
        return future[0] if future else None
    
    def get_next_crash(self) -> Optional[PromoEvent]:
        """Get the next major/extreme crash event."""
        now = datetime.now()
        crashes = [e for e in self.events 
                   if e.start_date > now and e.crash_severity in ['major', 'extreme']]
        return crashes[0] if crashes else None
    
    def days_until_event(self, event: PromoEvent) -> int:
        """Days until a specific event."""
        return (event.start_date - datetime.now()).days
    
    def get_weekly_phase(self) -> Dict:
        """
        Get current position in the weekly cycle.
        
        Key insight: Thursday rewards is the most important day.
        """
        now = datetime.now()
        day = now.weekday()  # 0=Mon, 6=Sun
        hour = now.hour
        
        phases = {
            0: {  # Monday
                'day': 'Monday',
                'phase': 'post_wl_selloff',
                'action': '🟢 BUY',
                'priority': 'high',
                'description': 'Weekend League ended. Players selling off squads.',
                'strategy': 'Secondary buy window. Good for sniping panic sellers.'
            },
            1: {  # Tuesday
                'day': 'Tuesday',
                'phase': 'recovery_start',
                'action': '🟢 BUY',
                'priority': 'medium',
                'description': 'Market stabilizing after sell-off.',
                'strategy': 'Last chance before Thursday demand.'
            },
            2: {  # Wednesday
                'day': 'Wednesday',
                'phase': 'pre_rewards_dip',
                'action': '🟢 BUY',
                'priority': 'high',
                'description': 'Players await Rivals rewards. Low liquidity = opportunities.',
                'strategy': 'BEST buying window before Thursday flood.'
            },
            3: {  # Thursday
                'day': 'Thursday',
                'phase': 'rewards_day',
                'action': '🟢🔴',
                'priority': 'critical',
                'description': 'MOST IMPORTANT DAY. Rivals rewards drop.',
                'strategy': 'Morning: BUY (packs flood market, -10-15%). Afternoon: prices recover. Evening: SELL prep.'
            },
            4: {  # Friday
                'day': 'Friday',
                'phase': 'content_and_wl_prep',
                'action': '🔴 SELL',
                'priority': 'high',
                'description': '6PM UK content drop. Weekend League prep.',
                'strategy': 'SELL meta cards. Peak demand as players finalize WL squads.'
            },
            5: {  # Saturday
                'day': 'Saturday',
                'phase': 'wl_active',
                'action': '⚪ HOLD',
                'priority': 'low',
                'description': 'Weekend League active. Stable prices.',
                'strategy': 'Avoid trading. Focus on playing or wait for Monday.'
            },
            6: {  # Sunday
                'day': 'Sunday',
                'phase': 'wl_ending',
                'action': '⚪ HOLD',
                'priority': 'low',
                'description': 'Weekend League winding down.',
                'strategy': 'Prepare buy list for Monday sell-off.'
            }
        }
        
        phase = phases[day]
        
        # Thursday has morning/afternoon/evening nuance
        if day == 3:
            if hour < 12:
                phase['substrategy'] = '🟢 MORNING: Buy now! Packs flooding market.'
            elif hour < 17:
                phase['substrategy'] = '🟡 AFTERNOON: Prices recovering. Hold or buy stragglers.'
            else:
                phase['substrategy'] = '🔴 EVENING: Demand rising. Sell if you have profits.'
        
        return phase
    
    def get_daily_windows(self) -> Dict:
        """Get optimal trading windows based on time of day."""
        now = datetime.now()
        hour = now.hour
        
        # Times are rough local approximations
        if 2 <= hour < 7:
            return {
                'window': 'Off-Peak (Night)',
                'action': '🟢 BUY',
                'description': 'Lowest demand. Overnight flipping opportunities.',
                'liquidity': 'low'
            }
        elif 7 <= hour < 12:
            return {
                'window': 'Morning',
                'action': '🟡 MIXED',
                'description': 'Moderate activity. EU waking up.',
                'liquidity': 'medium'
            }
        elif 12 <= hour < 17:
            return {
                'window': 'Afternoon',
                'action': '🟡 MIXED',
                'description': 'Building toward peak. NA coming online.',
                'liquidity': 'medium-high'
            }
        elif 17 <= hour < 22:
            return {
                'window': 'Peak Hours (6PM-10PM)',
                'action': '🔴 SELL',
                'description': 'Highest demand. Best time to sell.',
                'liquidity': 'high'
            }
        else:
            return {
                'window': 'Late Night',
                'action': '🟢 BUY',
                'description': 'Demand dropping. Deals appearing.',
                'liquidity': 'medium-low'
            }
    
    def is_content_drop_window(self) -> bool:
        """Check if we're near 6PM UK content drop (rough local approximation)."""
        hour = datetime.now().hour
        # This is approximate - would need timezone handling for accuracy
        return 17 <= hour <= 19
    
    def get_fodder_advice(self) -> Dict:
        """Get current fodder investment advice."""
        active = self.get_active_promo()
        next_crash = self.get_next_crash()
        weekly = self.get_weekly_phase()
        
        advice = {
            'low_fodder': {  # 82-84
                'name': '82-84 Rated',
                'current_action': 'HOLD',
                'notes': 'Buy between promos on Thursday. Sell when SBCs drop.'
            },
            'mid_fodder': {  # 85-87
                'name': '85-87 Rated',
                'current_action': 'HOLD',
                'notes': 'Steady demand. Can double during TOTY/TOTS.'
            },
            'high_fodder': {  # 88-91
                'name': '88-91 Rated',
                'current_action': 'HOLD',
                'notes': 'Gradual appreciation. Spike during Icon SBCs.'
            }
        }
        
        # Adjust based on context
        if active and active.crash_severity == 'extreme':
            advice['low_fodder']['current_action'] = '🟢 BUY'
            advice['low_fodder']['notes'] = 'Crash prices! Stock up.'
        
        if weekly['day'] == 'Thursday':
            advice['low_fodder']['current_action'] = '🟢 BUY'
            advice['low_fodder']['notes'] = 'Post-rewards flood. Cheapest day.'
        
        return advice


def get_calendar() -> FUTCalendar:
    """Get FUTCalendar instance."""
    return FUTCalendar()
