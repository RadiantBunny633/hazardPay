"""
Player Manager Module for HazardPay.
Handles player tracking, synchronization between scraper and database.
"""

import logging
from typing import Optional, List, Dict
from datetime import datetime

from .database import get_db, Database
from .scraper import FutbinScraper, PlayerPrice, scrape_player

logger = logging.getLogger(__name__)


class PlayerManager:
    """Manages player tracking and price synchronization."""
    
    def __init__(self, db: Database = None, platform: str = 'ps'):
        self.db = db or get_db()
        self.platform = platform
        self.scraper = FutbinScraper(platform=platform)
    
    # ========== Player Management ==========
    
    def add_player(
        self,
        futbin_id: int,
        name: str,
        slug: str = None,
        rating: int = None,
        position: str = None,
        version: str = None,
        fetch_initial_price: bool = True,
        backfill_history: bool = False
    ) -> Optional[Dict]:
        """
        Add a player to track and optionally fetch initial price.
        
        Args:
            futbin_id: Futbin's player ID
            name: Player display name
            slug: URL-friendly name (auto-generated if not provided)
            rating: Player rating
            position: Player position (ST, CAM, etc.)
            version: Card version (gold, icon, toty, etc.)
            fetch_initial_price: Whether to scrape initial price
            backfill_history: Whether to fetch historical prices from Futbin sales
        
        Returns:
            Dict with player info including any fetched price
        """
        if slug is None:
            slug = self._generate_slug(name)
        
        # Add to database
        player_id = self.db.add_player(
            futbin_id=futbin_id,
            name=name,
            slug=slug,
            rating=rating,
            position=position,
            version=version
        )
        
        if not player_id:
            logger.error(f"Failed to add player {name} ({futbin_id})")
            return None
        
        result = {
            'id': player_id,
            'futbin_id': futbin_id,
            'name': name,
            'slug': slug,
            'rating': rating,
            'position': position,
            'history_count': 0,
        }
        
        # Optionally fetch initial price
        if fetch_initial_price:
            price_data = self.scraper.get_player_prices(futbin_id, slug)
            if price_data and price_data.current_price:
                self.db.add_price(
                    player_id=player_id,
                    price=price_data.current_price,
                    platform=self.platform,
                    price_min=price_data.price_min,
                    price_max=price_data.price_max
                )
                result['current_price'] = price_data.current_price
                result['price_min'] = price_data.price_min
                result['price_max'] = price_data.price_max
        
        # Optionally backfill historical prices
        if backfill_history:
            history_count = self._backfill_history(player_id, futbin_id, slug)
            result['history_count'] = history_count
        
        logger.info(f"Added player: {name} (ID: {player_id}, Futbin: {futbin_id})")
        return result
    
    def _backfill_history(self, player_id: int, futbin_id: int, slug: str) -> int:
        """Fetch and store historical prices from Futbin sales page."""
        historical_prices = self.scraper.get_historical_prices(futbin_id, slug)
        
        if not historical_prices:
            logger.warning(f"No historical prices found for player {player_id}")
            return 0
        
        # Bulk insert historical prices
        count = 0
        for hp in historical_prices:
            self.db.add_price(
                player_id=player_id,
                price=hp.price,
                platform=self.platform,
                recorded_at=hp.timestamp
            )
            count += 1
        
        logger.info(f"Backfilled {count} historical prices for player {player_id}")
        return count
    
    def add_player_by_url(
        self, 
        url: str, 
        fetch_initial_price: bool = True,
        backfill_history: bool = False
    ) -> Optional[Dict]:
        """
        Add a player from a Futbin URL.
        
        Example URL: https://www.futbin.com/26/player/21407/cruyff/market
        """
        import re
        
        match = re.search(r'/player/(\d+)/([^/]+)', url)
        if not match:
            logger.error(f"Could not parse Futbin URL: {url}")
            return None
        
        futbin_id = int(match.group(1))
        slug = match.group(2)
        name = slug.replace('-', ' ').title()
        
        return self.add_player(
            futbin_id=futbin_id,
            name=name,
            slug=slug,
            fetch_initial_price=fetch_initial_price,
            backfill_history=backfill_history
        )
    
    def get_player(self, player_id: int = None, futbin_id: int = None) -> Optional[Dict]:
        """Get player info by internal or Futbin ID."""
        return self.db.get_player(player_id=player_id, futbin_id=futbin_id)
    
    def get_active_players(self) -> List[Dict]:
        """Get all players being actively tracked."""
        return self.db.get_active_players()
    
    def get_all_players(self) -> List[Dict]:
        """Get all players in database."""
        return self.db.get_all_players()
    
    def deactivate_player(self, player_id: int) -> bool:
        """Stop tracking a player (keeps historical data)."""
        success = self.db.set_player_active(player_id, active=False)
        if success:
            logger.info(f"Deactivated player {player_id}")
        return success
    
    def activate_player(self, player_id: int) -> bool:
        """Resume tracking a player."""
        success = self.db.set_player_active(player_id, active=True)
        if success:
            logger.info(f"Activated player {player_id}")
        return success
    
    def delete_player(self, player_id: int) -> bool:
        """Permanently delete a player and all their data."""
        success = self.db.delete_player(player_id)
        if success:
            logger.info(f"Deleted player {player_id}")
        return success
    
    # ========== Price Operations ==========
    
    def fetch_price(self, player_id: int) -> Optional[int]:
        """Fetch and store current price for a single player."""
        player = self.db.get_player(player_id=player_id)
        if not player:
            logger.error(f"Player {player_id} not found")
            return None
        
        price_data = self.scraper.get_player_prices(
            player['futbin_id'], 
            player['slug']
        )
        
        if not price_data or not price_data.current_price:
            logger.warning(f"Could not fetch price for {player['name']}")
            return None
        
        self.db.add_price(
            player_id=player_id,
            price=price_data.current_price,
            platform=self.platform,
            price_min=price_data.price_min,
            price_max=price_data.price_max
        )
        
        logger.info(f"Fetched price for {player['name']}: {price_data.current_price:,}")
        return price_data.current_price
    
    def fetch_all_prices(self) -> Dict[str, int]:
        """Fetch and store prices for all active players."""
        players = self.db.get_active_players()
        
        if not players:
            logger.warning("No active players to fetch prices for")
            return {'success': 0, 'failed': 0}
        
        logger.info(f"Fetching prices for {len(players)} players...")
        
        # Prepare player list for batch scraping
        player_list = [
            {'futbin_id': p['futbin_id'], 'slug': p['slug']}
            for p in players
        ]
        
        # Scrape all prices
        price_data_list = self.scraper.scrape_players(player_list)
        
        # Map futbin_id to player_id for database inserts
        futbin_to_player = {p['futbin_id']: p['id'] for p in players}
        
        # Prepare bulk insert
        prices_to_insert = []
        for pd in price_data_list:
            player_id = futbin_to_player.get(pd.futbin_id)
            if player_id and pd.current_price:
                prices_to_insert.append({
                    'player_id': player_id,
                    'price': pd.current_price,
                    'platform': self.platform,
                    'price_min': pd.price_min,
                    'price_max': pd.price_max,
                })
        
        # Bulk insert
        if prices_to_insert:
            inserted = self.db.add_prices_bulk(prices_to_insert)
            logger.info(f"Inserted {inserted} price records")
        
        success = len(prices_to_insert)
        failed = len(players) - success
        
        return {'success': success, 'failed': failed}
    
    def get_price_history(self, player_id: int, days: int = 30) -> List[Dict]:
        """Get price history for a player."""
        return self.db.get_price_history(player_id, platform=self.platform, days=days)
    
    def get_latest_price(self, player_id: int) -> Optional[int]:
        """Get the most recent price for a player."""
        price_record = self.db.get_latest_price(player_id, platform=self.platform)
        return price_record['price'] if price_record else None
    
    # ========== Watchlist Operations ==========
    
    def add_to_watchlist(
        self,
        player_id: int,
        target_buy_price: int = None,
        target_sell_price: int = None,
        notes: str = None
    ) -> bool:
        """Add a player to your investment watchlist."""
        result = self.db.add_to_watchlist(
            player_id=player_id,
            target_buy_price=target_buy_price,
            target_sell_price=target_sell_price,
            notes=notes
        )
        return result is not None
    
    def get_watchlist(self) -> List[Dict]:
        """Get all players on watchlist with current prices."""
        return self.db.get_watchlist()
    
    def remove_from_watchlist(self, player_id: int) -> bool:
        """Remove a player from watchlist."""
        return self.db.remove_from_watchlist(player_id)
    
    # ========== Utilities ==========
    
    def _generate_slug(self, name: str) -> str:
        """Generate a URL-friendly slug from a player name."""
        import re
        slug = name.lower()
        slug = re.sub(r"['\"]", '', slug)  # Remove quotes
        slug = re.sub(r'[^a-z0-9]+', '-', slug)  # Replace non-alphanumeric with dashes
        slug = slug.strip('-')
        return slug
    
    def import_players_bulk(self, players: List[Dict], fetch_prices: bool = False) -> Dict:
        """
        Bulk import players.
        
        Args:
            players: List of dicts with at least 'futbin_id' and 'name'
            fetch_prices: Whether to fetch initial prices (slower)
        
        Returns:
            Stats dict with 'added' and 'failed' counts
        """
        added = 0
        failed = 0
        
        for player in players:
            try:
                result = self.add_player(
                    futbin_id=player['futbin_id'],
                    name=player['name'],
                    slug=player.get('slug'),
                    rating=player.get('rating'),
                    position=player.get('position'),
                    version=player.get('version'),
                    fetch_initial_price=fetch_prices
                )
                if result:
                    added += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Failed to import player {player}: {e}")
                failed += 1
        
        return {'added': added, 'failed': failed}


# Default starter players - high-value icons/special cards
STARTER_PLAYERS = [
    {'futbin_id': 21407, 'name': 'Johan Cruyff', 'slug': 'cruyff', 'rating': 94, 'position': 'CF', 'version': 'icon'},
    {'futbin_id': 20689, 'name': 'Franck Ribéry', 'slug': 'ribery', 'rating': 87, 'position': 'LW', 'version': 'icon'},
    {'futbin_id': 21, 'name': 'Lionel Messi', 'slug': 'messi', 'rating': 90, 'position': 'RW', 'version': 'gold'},
    {'futbin_id': 20, 'name': 'Cristiano Ronaldo', 'slug': 'ronaldo', 'rating': 88, 'position': 'ST', 'version': 'gold'},
    {'futbin_id': 14, 'name': 'Kylian Mbappé', 'slug': 'mbappe', 'rating': 91, 'position': 'ST', 'version': 'gold'},
    {'futbin_id': 15, 'name': 'Erling Haaland', 'slug': 'haaland', 'rating': 91, 'position': 'ST', 'version': 'gold'},
    {'futbin_id': 50, 'name': 'Jude Bellingham', 'slug': 'bellingham', 'rating': 90, 'position': 'CM', 'version': 'gold'},
]


def get_manager(platform: str = 'ps') -> PlayerManager:
    """Get a PlayerManager instance."""
    return PlayerManager(platform=platform)
