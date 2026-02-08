"""
Portfolio & Position Management for HazardPay.
Tracks bought positions and calculates P&L.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum

from .database import get_db, Database

logger = logging.getLogger(__name__)


class PositionType(Enum):
    """Investment tier types."""
    FODDER = "fodder"      # Low stake: TOTWs, 82-87 rated (5-20k investments)
    META = "meta"          # High stake: Icons, Heroes, meta golds (100k+ investments)


@dataclass
class Position:
    """A bought position."""
    id: str
    player_id: str
    player_name: str
    futbin_id: int
    position_type: PositionType
    buy_price: int
    buy_date: datetime
    quantity: int
    target_sell_price: Optional[int]
    notes: str
    
    # Calculated fields (populated when fetching)
    current_price: Optional[int] = None
    profit_loss: Optional[int] = None
    profit_pct: Optional[float] = None


class Portfolio:
    """Manages trading positions."""
    
    def __init__(self, db: Database = None, platform: str = 'ps'):
        self.db = db or get_db()
        self.platform = platform
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Ensure portfolio collection exists."""
        if 'portfolio' not in self.db.db.list_collection_names():
            self.db.db.create_collection('portfolio')
            self.db.db.portfolio.create_index('player_id')
            self.db.db.portfolio.create_index('status')
    
    def add_position(
        self,
        player_id: str,
        buy_price: int,
        quantity: int = 1,
        position_type: str = 'meta',
        target_sell_price: int = None,
        notes: str = ''
    ) -> Optional[str]:
        """
        Record a bought position.
        
        Args:
            player_id: Database player ID
            buy_price: Price paid per card
            quantity: Number of cards bought
            position_type: 'fodder' or 'meta'
            target_sell_price: Optional target to sell at
            notes: Any notes about the trade
        """
        player = self.db.get_player(player_id=player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return None
        
        position_doc = {
            'player_id': player_id,
            'player_name': player['name'],
            'futbin_id': player['futbin_id'],
            'position_type': position_type,
            'buy_price': buy_price,
            'buy_date': datetime.now(),
            'quantity': quantity,
            'target_sell_price': target_sell_price,
            'notes': notes,
            'status': 'open',  # open, closed
            'sell_price': None,
            'sell_date': None,
            'platform': self.platform
        }
        
        result = self.db.db.portfolio.insert_one(position_doc)
        logger.info(f"Added position: {player['name']} x{quantity} @ {buy_price:,}")
        return str(result.inserted_id)
    
    def close_position(self, position_id: str, sell_price: int) -> bool:
        """Close a position (record the sale)."""
        from bson import ObjectId
        
        result = self.db.db.portfolio.update_one(
            {'_id': ObjectId(position_id)},
            {
                '$set': {
                    'status': 'closed',
                    'sell_price': sell_price,
                    'sell_date': datetime.now()
                }
            }
        )
        return result.modified_count > 0
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions with current P&L."""
        positions = list(self.db.db.portfolio.find({'status': 'open'}))
        
        for pos in positions:
            pos['id'] = str(pos.pop('_id'))
            
            # Get current price
            latest = self.db.get_latest_price(pos['player_id'], platform=self.platform)
            if latest:
                pos['current_price'] = latest['price']
                pos['profit_loss'] = (latest['price'] - pos['buy_price']) * pos['quantity']
                pos['profit_pct'] = ((latest['price'] - pos['buy_price']) / pos['buy_price']) * 100
                
                # Factor in EA tax (5%)
                sell_after_tax = int(latest['price'] * 0.95)
                pos['profit_after_tax'] = (sell_after_tax - pos['buy_price']) * pos['quantity']
                pos['profit_pct_after_tax'] = ((sell_after_tax - pos['buy_price']) / pos['buy_price']) * 100
            else:
                pos['current_price'] = None
                pos['profit_loss'] = None
                pos['profit_pct'] = None
        
        return positions
    
    def get_closed_positions(self, days: int = 30) -> List[Dict]:
        """Get closed positions from last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        positions = list(self.db.db.portfolio.find({
            'status': 'closed',
            'sell_date': {'$gte': cutoff}
        }))
        
        for pos in positions:
            pos['id'] = str(pos.pop('_id'))
            pos['profit_loss'] = (pos['sell_price'] - pos['buy_price']) * pos['quantity']
            pos['profit_pct'] = ((pos['sell_price'] - pos['buy_price']) / pos['buy_price']) * 100
            
            # After tax
            sell_after_tax = int(pos['sell_price'] * 0.95)
            pos['profit_after_tax'] = (sell_after_tax - pos['buy_price']) * pos['quantity']
        
        return positions
    
    def get_portfolio_summary(self) -> Dict:
        """Get overall portfolio statistics."""
        open_positions = self.get_open_positions()
        closed_positions = self.get_closed_positions(days=30)
        
        # Open positions stats
        total_invested = sum(p['buy_price'] * p['quantity'] for p in open_positions)
        current_value = sum(
            p['current_price'] * p['quantity'] 
            for p in open_positions 
            if p.get('current_price')
        )
        unrealized_pl = sum(
            p['profit_after_tax'] 
            for p in open_positions 
            if p.get('profit_after_tax')
        )
        
        # Closed positions stats
        realized_pl = sum(p['profit_after_tax'] for p in closed_positions)
        wins = len([p for p in closed_positions if p['profit_after_tax'] > 0])
        losses = len([p for p in closed_positions if p['profit_after_tax'] < 0])
        
        return {
            'open_positions': len(open_positions),
            'total_invested': total_invested,
            'current_value': current_value,
            'unrealized_pl': unrealized_pl,
            'unrealized_pct': (unrealized_pl / total_invested * 100) if total_invested else 0,
            'closed_30d': len(closed_positions),
            'realized_pl_30d': realized_pl,
            'win_rate': (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0,
            'wins': wins,
            'losses': losses
        }
    
    def delete_position(self, position_id: str) -> bool:
        """Delete a position entirely."""
        from bson import ObjectId
        result = self.db.db.portfolio.delete_one({'_id': ObjectId(position_id)})
        return result.deleted_count > 0


def get_portfolio(platform: str = 'ps') -> Portfolio:
    """Get Portfolio instance."""
    return Portfolio(platform=platform)
