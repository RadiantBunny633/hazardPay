"""
Database module for HazardPay.
Handles MongoDB connections and CRUD operations.
"""

from pymongo import MongoClient, DESCENDING, ASCENDING
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

logger = logging.getLogger(__name__)


class Database:
    """MongoDB database handler."""
    
    def __init__(self):
        self.client = None
        self.db = None
        self._connect()
    
    def _connect(self):
        """Connect to MongoDB."""
        uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/hazardpay')
        db_name = os.getenv('DB_NAME', 'hazardpay')
        
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        
        # Create indexes on first connection
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create indexes for performance."""
        # Players collection
        self.db.players.create_index('futbin_id', unique=True)
        self.db.players.create_index('is_active')
        self.db.players.create_index('name')
        
        # Price history collection
        self.db.price_history.create_index([('player_id', ASCENDING), ('recorded_at', DESCENDING)])
        self.db.price_history.create_index([('platform', ASCENDING), ('recorded_at', DESCENDING)])
        
        # Alerts collection
        self.db.alerts.create_index([('is_read', ASCENDING), ('created_at', DESCENDING)])
        
        # Watchlist collection
        self.db.watchlist.create_index('player_id', unique=True)

        # Signal log collection (diagnostic logging for score analysis)
        self.db.signal_log.create_index([('player_id', ASCENDING), ('timestamp', DESCENDING)])
        self.db.signal_log.create_index('timestamp', expireAfterSeconds=30*24*3600)  # 30-day TTL

        # Players card_type index (for ML pipeline grouping)
        self.db.players.create_index('card_type')

        # Labeled signals collection (permanent training data, no TTL)
        self.db.labeled_signals.create_index('signal_id', unique=True)
        self.db.labeled_signals.create_index([('card_type', ASCENDING), ('direction', ASCENDING)])
        self.db.labeled_signals.create_index('signal_timestamp')
    
    def init_schema(self, schema_path: str = None):
        """Initialize database (MongoDB doesn't need schema, just ensures indexes)."""
        self._ensure_indexes()
        logger.info("Database indexes created successfully")
        return True
    
    # ========== Player Operations ==========
    
    def add_player(
        self,
        futbin_id: int,
        name: str,
        slug: str = None,
        rating: int = None,
        position: str = None,
        version: str = None,
        league: str = None,
        nation: str = None,
        club: str = None
    ) -> Optional[str]:
        """Add a new player to track. Returns player ID."""
        if slug is None:
            slug = name.lower().replace(' ', '-').replace("'", "")
        
        player_doc = {
            'futbin_id': futbin_id,
            'name': name,
            'slug': slug,
            'rating': rating,
            'position': position,
            'version': version,
            'league': league,
            'nation': nation,
            'club': club,
            'is_active': True,
            'updated_at': datetime.now()
        }
        
        # Upsert - update if exists, insert if not
        result = self.db.players.update_one(
            {'futbin_id': futbin_id},
            {'$set': player_doc, '$setOnInsert': {'created_at': datetime.now()}},
            upsert=True
        )
        
        # Get the player ID
        player = self.db.players.find_one({'futbin_id': futbin_id})
        return str(player['_id']) if player else None
    
    def get_player(self, player_id: str = None, futbin_id: int = None) -> Optional[Dict]:
        """Get a player by internal ID or Futbin ID."""
        from bson import ObjectId
        
        if player_id:
            try:
                player = self.db.players.find_one({'_id': ObjectId(player_id)})
            except:
                return None
        elif futbin_id:
            player = self.db.players.find_one({'futbin_id': futbin_id})
        else:
            return None
        
        if player:
            player['id'] = str(player.pop('_id'))
            return player
        return None
    
    def get_active_players(self) -> List[Dict]:
        """Get all players marked as active for tracking."""
        players = list(self.db.players.find(
            {'is_active': True}
        ).sort([('rating', DESCENDING), ('name', ASCENDING)]))
        
        for p in players:
            p['id'] = str(p.pop('_id'))
        return players
    
    def get_all_players(self) -> List[Dict]:
        """Get all players."""
        players = list(self.db.players.find().sort([('rating', DESCENDING), ('name', ASCENDING)]))
        for p in players:
            p['id'] = str(p.pop('_id'))
        return players
    
    def set_player_active(self, player_id: str, active: bool = True) -> bool:
        """Enable or disable tracking for a player."""
        from bson import ObjectId
        
        result = self.db.players.update_one(
            {'_id': ObjectId(player_id)},
            {'$set': {'is_active': active, 'updated_at': datetime.now()}}
        )
        return result.modified_count > 0
    
    def delete_player(self, player_id: str) -> bool:
        """Delete a player and all associated data."""
        from bson import ObjectId
        
        # Delete associated data
        self.db.price_history.delete_many({'player_id': player_id})
        self.db.alerts.delete_many({'player_id': player_id})
        self.db.watchlist.delete_many({'player_id': player_id})
        
        # Delete player
        result = self.db.players.delete_one({'_id': ObjectId(player_id)})
        return result.deleted_count > 0
    
    # ========== Price History Operations ==========
    
    def add_price(
        self,
        player_id: str,
        price: int,
        platform: str = 'ps',
        price_min: int = None,
        price_max: int = None,
        recorded_at: datetime = None
    ) -> Optional[str]:
        """Record a price snapshot for a player."""
        price_doc = {
            'player_id': player_id,
            'price': price,
            'platform': platform,
            'price_min': price_min,
            'price_max': price_max,
            'recorded_at': recorded_at or datetime.now()
        }
        
        result = self.db.price_history.insert_one(price_doc)
        return str(result.inserted_id) if result.inserted_id else None
    
    def add_prices_bulk(self, prices: List[Dict]) -> int:
        """Bulk insert price records."""
        if not prices:
            return 0
        
        price_docs = []
        for p in prices:
            price_docs.append({
                'player_id': p['player_id'],
                'price': p['price'],
                'platform': p.get('platform', 'ps'),
                'price_min': p.get('price_min'),
                'price_max': p.get('price_max'),
                'recorded_at': datetime.now()
            })
        
        result = self.db.price_history.insert_many(price_docs)
        return len(result.inserted_ids)
    
    def get_price_history(
        self,
        player_id: str,
        platform: str = 'ps',
        days: int = 30,
        limit: int = None
    ) -> List[Dict]:
        """Get price history for a player."""
        cutoff = datetime.now() - timedelta(days=days)
        
        query = {
            'player_id': player_id,
            'platform': platform,
            'recorded_at': {'$gte': cutoff}
        }
        
        cursor = self.db.price_history.find(query).sort('recorded_at', DESCENDING)
        
        if limit:
            cursor = cursor.limit(limit)
        
        prices = list(cursor)
        for p in prices:
            p['id'] = str(p.pop('_id'))
        return prices
    
    def get_latest_price(self, player_id: str, platform: str = 'ps') -> Optional[Dict]:
        """Get the most recent price for a player."""
        price = self.db.price_history.find_one(
            {'player_id': player_id, 'platform': platform},
            sort=[('recorded_at', DESCENDING)]
        )
        
        if price:
            price['id'] = str(price.pop('_id'))
            return price
        return None
    
    def get_latest_prices_all(self, platform: str = 'ps') -> List[Dict]:
        """Get latest prices for all active players."""
        players = self.get_active_players()
        results = []
        
        for player in players:
            latest = self.get_latest_price(player['id'], platform)
            if latest:
                results.append({
                    'id': player['id'],
                    'futbin_id': player['futbin_id'],
                    'name': player['name'],
                    'rating': player.get('rating'),
                    'position': player.get('position'),
                    'price': latest['price'],
                    'platform': platform,
                    'recorded_at': latest['recorded_at']
                })
        
        return results
    
    # ========== Price Alerts Operations ==========
    
    def add_alert(
        self,
        player_id: str,
        alert_type: str,
        message: str,
        price_at_alert: int
    ) -> Optional[str]:
        """Create a price alert."""
        alert_doc = {
            'player_id': player_id,
            'alert_type': alert_type,
            'message': message,
            'price_at_alert': price_at_alert,
            'is_read': False,
            'created_at': datetime.now()
        }
        
        result = self.db.alerts.insert_one(alert_doc)
        return str(result.inserted_id) if result.inserted_id else None
    
    def get_unread_alerts(self, limit: int = 50) -> List[Dict]:
        """Get unread price alerts."""
        from bson import ObjectId
        
        alerts = list(self.db.alerts.find(
            {'is_read': False}
        ).sort('created_at', DESCENDING).limit(limit))
        
        results = []
        for a in alerts:
            # Get player info
            player = None
            try:
                player = self.db.players.find_one({'_id': ObjectId(a['player_id'])})
            except:
                pass
            
            results.append({
                'id': str(a['_id']),
                'player_id': a['player_id'],
                'name': player['name'] if player else 'Unknown',
                'rating': player.get('rating') if player else None,
                'futbin_id': player.get('futbin_id') if player else None,
                'alert_type': a['alert_type'],
                'message': a['message'],
                'price_at_alert': a['price_at_alert'],
                'is_read': a['is_read'],
                'created_at': a['created_at']
            })
        
        return results
    
    def mark_alerts_read(self, alert_ids: List[str] = None) -> int:
        """Mark alerts as read."""
        from bson import ObjectId
        
        if alert_ids:
            result = self.db.alerts.update_many(
                {'_id': {'$in': [ObjectId(aid) for aid in alert_ids]}},
                {'$set': {'is_read': True}}
            )
        else:
            result = self.db.alerts.update_many(
                {'is_read': False},
                {'$set': {'is_read': True}}
            )
        return result.modified_count
    
    # ========== Watchlist Operations ==========
    
    def add_to_watchlist(
        self,
        player_id: str,
        target_buy_price: int = None,
        target_sell_price: int = None,
        notes: str = None
    ) -> Optional[str]:
        """Add a player to watchlist."""
        watchlist_doc = {
            'player_id': player_id,
            'target_buy_price': target_buy_price,
            'target_sell_price': target_sell_price,
            'notes': notes,
            'added_at': datetime.now()
        }
        
        result = self.db.watchlist.update_one(
            {'player_id': player_id},
            {'$set': watchlist_doc},
            upsert=True
        )
        
        return player_id if result.upserted_id or result.modified_count or result.matched_count else None
    
    def get_watchlist(self) -> List[Dict]:
        """Get all players on watchlist with current prices."""
        from bson import ObjectId
        
        watchlist_items = list(self.db.watchlist.find().sort('added_at', DESCENDING))
        
        results = []
        for item in watchlist_items:
            try:
                player = self.db.players.find_one({'_id': ObjectId(item['player_id'])})
            except:
                continue
                
            if not player:
                continue
            
            latest = self.get_latest_price(item['player_id'], 'ps')
            
            results.append({
                'id': str(item['_id']),
                'player_id': item['player_id'],
                'name': player['name'],
                'rating': player.get('rating'),
                'futbin_id': player['futbin_id'],
                'slug': player.get('slug'),
                'target_buy_price': item.get('target_buy_price'),
                'target_sell_price': item.get('target_sell_price'),
                'notes': item.get('notes'),
                'current_price': latest['price'] if latest else None,
                'price_updated_at': latest['recorded_at'] if latest else None,
                'added_at': item['added_at']
            })
        
        return results
    
    def remove_from_watchlist(self, player_id: str) -> bool:
        """Remove a player from watchlist."""
        result = self.db.watchlist.delete_one({'player_id': player_id})
        return result.deleted_count > 0
    
    # ========== Analytics Queries ==========
    
    def get_price_drops(self, threshold_pct: float = 10, platform: str = 'ps') -> List[Dict]:
        """Get players whose price dropped by more than threshold in 24 hours."""
        players = self.get_active_players()
        drops = []
        
        now = datetime.now()
        yesterday = now - timedelta(hours=24)
        two_days_ago = now - timedelta(hours=48)
        
        for player in players:
            # Get current price (last 24h)
            current = self.db.price_history.find_one(
                {'player_id': player['id'], 'platform': platform, 'recorded_at': {'$gte': yesterday}},
                sort=[('recorded_at', DESCENDING)]
            )
            
            # Get previous price (24-48h ago)
            previous = self.db.price_history.find_one(
                {'player_id': player['id'], 'platform': platform, 
                 'recorded_at': {'$gte': two_days_ago, '$lt': yesterday}},
                sort=[('recorded_at', DESCENDING)]
            )
            
            if current and previous and previous['price'] > 0:
                pct_change = ((current['price'] - previous['price']) / previous['price']) * 100
                
                if pct_change <= -threshold_pct:
                    drops.append({
                        'id': player['id'],
                        'name': player['name'],
                        'rating': player.get('rating'),
                        'platform': platform,
                        'current_price': current['price'],
                        'previous_price': previous['price'],
                        'price_change': current['price'] - previous['price'],
                        'pct_change': round(pct_change, 2)
                    })
        
        drops.sort(key=lambda x: x['pct_change'])
        return drops
    
    def get_price_spikes(self, threshold_pct: float = 10, platform: str = 'ps') -> List[Dict]:
        """Get players whose price increased by more than threshold in 24 hours."""
        players = self.get_active_players()
        spikes = []
        
        now = datetime.now()
        yesterday = now - timedelta(hours=24)
        two_days_ago = now - timedelta(hours=48)
        
        for player in players:
            current = self.db.price_history.find_one(
                {'player_id': player['id'], 'platform': platform, 'recorded_at': {'$gte': yesterday}},
                sort=[('recorded_at', DESCENDING)]
            )
            
            previous = self.db.price_history.find_one(
                {'player_id': player['id'], 'platform': platform,
                 'recorded_at': {'$gte': two_days_ago, '$lt': yesterday}},
                sort=[('recorded_at', DESCENDING)]
            )
            
            if current and previous and previous['price'] > 0:
                pct_change = ((current['price'] - previous['price']) / previous['price']) * 100
                
                if pct_change >= threshold_pct:
                    spikes.append({
                        'id': player['id'],
                        'name': player['name'],
                        'rating': player.get('rating'),
                        'platform': platform,
                        'current_price': current['price'],
                        'previous_price': previous['price'],
                        'price_change': current['price'] - previous['price'],
                        'pct_change': round(pct_change, 2)
                    })
        
        spikes.sort(key=lambda x: x['pct_change'], reverse=True)
        return spikes
    
    # ========== Signal Log Operations ==========

    def log_signal(self, signal_data: Dict) -> Optional[str]:
        """Log a signal score with component breakdown for diagnostics."""
        signal_data['timestamp'] = datetime.now()
        result = self.db.signal_log.insert_one(signal_data)
        return str(result.inserted_id) if result.inserted_id else None

    def get_signal_logs(self, player_id: str = None, direction: str = None,
                        hours: int = 24, limit: int = 50) -> List[Dict]:
        """Query signal logs with filters."""
        query = {'timestamp': {'$gte': datetime.now() - timedelta(hours=hours)}}
        if player_id:
            query['player_id'] = player_id
        if direction:
            query['direction'] = direction

        logs = list(self.db.signal_log.find(query).sort('timestamp', DESCENDING).limit(limit))
        for log in logs:
            log['id'] = str(log.pop('_id'))
        return logs

    def get_signal_summary(self, player_id: str, hours: int = 24) -> Optional[Dict]:
        """Get aggregated signal stats for a player."""
        cutoff = datetime.now() - timedelta(hours=hours)
        logs = list(self.db.signal_log.find({
            'player_id': player_id,
            'timestamp': {'$gte': cutoff}
        }))

        if not logs:
            return None

        scores = [l['final_score'] for l in logs]
        return {
            'count': len(logs),
            'avg_score': sum(scores) / len(scores),
            'min_score': min(scores),
            'max_score': max(scores),
            'latest_score': logs[0]['final_score'] if logs else None,
            'directions': {
                'BUY': len([l for l in logs if l.get('direction') == 'BUY']),
                'SELL': len([l for l in logs if l.get('direction') == 'SELL']),
            }
        }

    # ========== Player Metadata Operations ==========

    def update_player_metadata(self, futbin_id: int, card_type: str,
                               first_seen_at: datetime = None,
                               version_raw: str = None) -> bool:
        """Update enriched metadata fields on a player."""
        update = {
            '$set': {
                'card_type': card_type,
                'updated_at': datetime.now()
            }
        }
        if first_seen_at:
            update['$set']['first_seen_at'] = first_seen_at
        if version_raw:
            update['$set']['version_raw'] = version_raw

        result = self.db.players.update_one(
            {'futbin_id': futbin_id},
            update
        )
        return result.modified_count > 0

    def get_volatility_scores(self, days: int = 7, platform: str = 'ps') -> List[Dict]:
        """Calculate price volatility for players over N days."""
        import statistics
        
        players = self.get_active_players()
        volatility_data = []
        
        cutoff = datetime.now() - timedelta(days=days)
        
        for player in players:
            prices = list(self.db.price_history.find(
                {'player_id': player['id'], 'platform': platform, 'recorded_at': {'$gte': cutoff}}
            ))
            
            if len(prices) < 3:
                continue
            
            price_values = [p['price'] for p in prices]
            avg_price = statistics.mean(price_values)
            std_dev = statistics.stdev(price_values)
            volatility_pct = (std_dev / avg_price) * 100 if avg_price > 0 else 0
            
            volatility_data.append({
                'id': player['id'],
                'name': player['name'],
                'rating': player.get('rating'),
                'futbin_id': player['futbin_id'],
                'data_points': len(prices),
                'avg_price': avg_price,
                'std_dev': std_dev,
                'volatility_pct': round(volatility_pct, 2)
            })
        
        volatility_data.sort(key=lambda x: x['volatility_pct'], reverse=True)
        return volatility_data


# Singleton instance
_db = None

def get_db() -> Database:
    """Get the database singleton instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db
