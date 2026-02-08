"""
Futbin Scraper Module for HazardPay.
Fetches player prices and market data from Futbin.
"""

import requests
from bs4 import BeautifulSoup
import time
import re
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PlayerPrice:
    """Container for scraped player price data."""
    futbin_id: int
    name: str
    current_price: Optional[int]
    recent_prices: List[int]
    price_min: Optional[int]
    price_max: Optional[int]
    platform: str
    scraped_at: datetime
    
    # Optional metadata
    rating: Optional[int] = None
    position: Optional[str] = None
    version: Optional[str] = None


@dataclass
class SaleRecord:
    """Container for individual sale from sales history."""
    timestamp: datetime
    listed_price: int
    sold_price: int
    ea_tax: int
    net_price: int
    sale_type: str


@dataclass
class HistoricalPrice:
    """Container for a historical price point from the sales chart."""
    timestamp: datetime
    price: int
    date_str: str


class FutbinScraper:
    """Scraper for Futbin player market pages."""
    
    def __init__(self, platform: str = None):
        self.platform = platform or Config.DEFAULT_PLATFORM
        self.delay = Config.SCRAPE_DELAY
        self.timeout = Config.REQUEST_TIMEOUT
        # Note: Futbin bot detection triggers on complex header sets
        # Keep headers minimal - just User-Agent works best
        self.headers = {
            'User-Agent': 'Mozilla/5.0',
        }
        self._last_request_time = 0
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(self, url: str) -> Optional[requests.Response]:
        """Make a rate-limited HTTP request."""
        self._rate_limit()
        
        try:
            # Use simple request instead of session - Futbin bot detection is aggressive
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error for {url}: {e}")
            return None
        except requests.exceptions.Timeout:
            logger.error(f"Request timed out for {url}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None
    
    def _parse_price(self, price_str: str) -> Optional[int]:
        """Parse a price string to integer (handles commas, 'K', 'M')."""
        if not price_str:
            return None
        
        price_str = price_str.strip().upper().replace(',', '').replace(' ', '')
        
        try:
            if 'M' in price_str:
                return int(float(price_str.replace('M', '')) * 1_000_000)
            elif 'K' in price_str:
                return int(float(price_str.replace('K', '')) * 1_000)
            else:
                return int(price_str)
        except (ValueError, TypeError):
            return None
    
    def _get_platform_selector(self) -> str:
        """Get the CSS class for platform-specific price boxes."""
        return f"platform-{self.platform}-only"
    
    def get_player_url(self, futbin_id: int, slug: str) -> str:
        """Build the Futbin market URL for a player."""
        return f"{Config.FUTBIN_BASE_URL}/player/{futbin_id}/{slug}/market"
    
    def get_player_prices(self, futbin_id: int, slug: str) -> Optional[PlayerPrice]:
        """
        Scrape current price data for a player.
        
        Args:
            futbin_id: Futbin's player ID
            slug: URL-friendly player name (e.g., 'cruyff', 'ribery')
        
        Returns:
            PlayerPrice object or None if scraping failed
        """
        url = self.get_player_url(futbin_id, slug)
        logger.info(f"Scraping: {url}")
        
        response = self._make_request(url)
        if not response:
            return None
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Get the platform-specific price box
        platform_class = self._get_platform_selector()
        price_box = soup.select_one(f'div.price-box.{platform_class}')
        
        if not price_box:
            # Fallback: try to find any price box
            price_box = soup.select_one('div.price-box')
        
        current_price = None
        recent_prices = []
        price_min = None
        price_max = None
        
        # Current lowest price
        price_el = soup.select_one('div.price.inline-with-icon.lowest-price-1')
        if price_el:
            current_price = self._parse_price(price_el.text)
        
        # Recent prices from data attribute
        graph_el = soup.select_one('[data-recent-prices]')
        if graph_el:
            prices_str = graph_el.get('data-recent-prices', '')
            recent_prices = [
                int(p) for p in prices_str.split(',') 
                if p and p.strip().isdigit()
            ]
        
        # Price range
        price_range_section = soup.find(string=re.compile(r'PRICE RANGE', re.I))
        if price_range_section:
            parent = price_range_section.find_parent()
            if parent:
                range_text = parent.get_text()
                range_match = re.search(r'([\d,]+)\s*-\s*([\d,]+)', range_text)
                if range_match:
                    price_min = self._parse_price(range_match.group(1))
                    price_max = self._parse_price(range_match.group(2))
        
        # Try to get player metadata from page
        rating = None
        position = None
        
        # Rating is often in a specific element
        rating_el = soup.select_one('.pcdisplay-rat')
        if rating_el:
            try:
                rating = int(rating_el.text.strip())
            except ValueError:
                pass
        
        # Position
        pos_el = soup.select_one('.pcdisplay-pos')
        if pos_el:
            position = pos_el.text.strip()
        
        return PlayerPrice(
            futbin_id=futbin_id,
            name=slug.replace('-', ' ').title(),
            current_price=current_price,
            recent_prices=recent_prices,
            price_min=price_min,
            price_max=price_max,
            platform=self.platform,
            scraped_at=datetime.now(),
            rating=rating,
            position=position
        )
    
    def get_sales_history(self, futbin_id: int, slug: str, limit: int = 20) -> List[SaleRecord]:
        """
        Scrape recent sales history for a player.
        Note: This parses the sales table on the market page.
        
        Args:
            futbin_id: Futbin's player ID
            slug: URL-friendly player name
            limit: Maximum number of sales to return
        
        Returns:
            List of SaleRecord objects
        """
        url = self.get_player_url(futbin_id, slug)
        logger.info(f"Scraping sales history: {url}")
        
        response = self._make_request(url)
        if not response:
            return []
        
        soup = BeautifulSoup(response.text, 'lxml')
        sales = []
        
        # Find sales history table
        sales_table = soup.select_one('table.table')
        if not sales_table:
            return []
        
        rows = sales_table.select('tbody tr')
        for row in rows[:limit]:
            cells = row.select('td')
            if len(cells) < 5:
                continue
            
            try:
                # Parse timestamp (format varies)
                timestamp_str = cells[0].text.strip()
                # Attempt to parse - adjust format as needed
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    timestamp = datetime.now()  # Fallback
                
                sale = SaleRecord(
                    timestamp=timestamp,
                    listed_price=self._parse_price(cells[1].text) or 0,
                    sold_price=self._parse_price(cells[2].text) or 0,
                    ea_tax=self._parse_price(cells[3].text) or 0,
                    net_price=self._parse_price(cells[4].text) or 0,
                    sale_type=cells[5].text.strip() if len(cells) > 5 else 'Unknown'
                )
                sales.append(sale)
            except Exception as e:
                logger.warning(f"Failed to parse sale row: {e}")
                continue
        
        return sales
    
    def get_historical_prices(self, futbin_id: int, slug: str) -> List[HistoricalPrice]:
        """
        Fetch historical price data from the Futbin sales page.
        This extracts the chart data which contains up to 500 price points.
        
        Args:
            futbin_id: Futbin's player ID
            slug: URL-friendly player name
        
        Returns:
            List of HistoricalPrice objects with timestamps and prices
        """
        import json
        
        url = f"{Config.FUTBIN_BASE_URL}/sales/{futbin_id}/{slug}?platform={self.platform}"
        logger.info(f"Fetching historical prices: {url}")
        
        response = self._make_request(url)
        if not response:
            return []
        
        # Extract chart data from the highcharts config embedded in HTML
        # The data is in format: "data":[{"name":"Feb 2 2026 23:49 pm","x":timestamp,"y":price},...]
        match = re.search(r'"series":\s*\[\s*\{[^}]*"data":\s*(\[[^\]]+\])', response.text)
        
        if not match:
            logger.warning(f"Could not find historical data for {slug}")
            return []
        
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse historical data JSON: {e}")
            return []
        
        historical_prices = []
        for entry in data:
            try:
                # x is timestamp in milliseconds, y is price
                timestamp_ms = entry.get('x')
                price = entry.get('y')
                date_str = entry.get('name', '')
                
                if timestamp_ms and price:
                    timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
                    historical_prices.append(HistoricalPrice(
                        timestamp=timestamp,
                        price=int(price),
                        date_str=date_str
                    ))
            except Exception as e:
                logger.warning(f"Failed to parse historical entry: {e}")
                continue
        
        logger.info(f"Found {len(historical_prices)} historical price points for {slug}")
        return historical_prices
    
    def get_daily_prices(self, futbin_id: int, slug: str) -> List[Dict]:
        """
        Fetch historical prices and aggregate to daily averages.
        Useful for getting one price point per day for cleaner analysis.
        
        Returns:
            List of dicts with 'date', 'avg_price', 'min_price', 'max_price', 'count'
        """
        from collections import defaultdict
        
        historical = self.get_historical_prices(futbin_id, slug)
        if not historical:
            return []
        
        # Group by date
        daily = defaultdict(list)
        for hp in historical:
            date_key = hp.timestamp.strftime('%Y-%m-%d')
            daily[date_key].append(hp.price)
        
        # Aggregate
        result = []
        for date_str, prices in sorted(daily.items()):
            result.append({
                'date': date_str,
                'avg_price': int(sum(prices) / len(prices)),
                'min_price': min(prices),
                'max_price': max(prices),
                'count': len(prices)
            })
        
        return result
    
    def get_longterm_daily_prices(self, futbin_id: int, slug: str, max_cache_hours: int = 6, cache_only: bool = False) -> Optional[Dict]:
        """
        Fetch the FULL historical daily price data from the player page.
        This gives data since card release (weeks/months of data), not just recent sales.

        Results are CACHED in MongoDB for speed. Use max_cache_hours to control freshness.

        The player page embeds multiple price arrays - we want the PS daily one
        which typically has the most data points going back to release.

        Args:
            futbin_id: Futbin player ID
            slug: URL slug for the player
            max_cache_hours: Use cached data if less than this old (default 6 hours)
            cache_only: If True, return cached data even if stale (never make network request).
                        Returns None only if no cache entry exists at all.

        Returns:
            Dict with 'prices' list of [timestamp_ms, price] and stats:
            - all_time_low, all_time_high, current
            - position_in_range (0-100%, where 0% = floor, 100% = peak)
            - floor_date, date_range
        """
        import json
        from datetime import timedelta

        # Try to get from cache first
        try:
            from .database import get_db
            db = get_db()

            cache_key = f"{futbin_id}_{self.platform}"
            cached = db.db.longterm_cache.find_one({'cache_key': cache_key})

            if cached:
                cache_age = datetime.now() - cached['cached_at']
                is_fresh = cache_age < timedelta(hours=max_cache_hours)

                if is_fresh or cache_only:
                    # Check for negative cache entry (player has no long-term data)
                    if cached.get('no_data') == True:
                        logger.debug(f"Skipping {slug} - cached as no long-term data available")
                        return None
                    # Return cached data
                    if cached.get('data'):
                        return cached.get('data')
        except Exception as e:
            logger.debug(f"Cache check failed: {e}")

        # In cache_only mode, don't make network requests
        if cache_only:
            logger.debug(f"No cached data for {slug} (cache_only=True)")
            return None
        
        # Fetch fresh data
        url = f"{Config.FUTBIN_BASE_URL}/player/{futbin_id}/{slug}"
        logger.info(f"Fetching long-term daily prices: {url}")
        
        response = self._make_request(url)
        if not response:
            return None
        
        # Find all arrays that look like daily price data [[timestamp, price], ...]
        all_matches = list(re.finditer(r'\[\[1\d{12},\d+\](?:,\[1\d{12},\d+\])+\]', response.text))
        
        # We need to find the DAILY data array, not hourly
        # Daily data: ~60-90 entries covering months (one per day)
        # Hourly data: 300+ entries covering just a few days
        # The key is to find arrays where timestamps are ~24 hours apart
        
        best_data = None
        best_score = 0
        
        for match in all_matches:
            try:
                data = json.loads(match.group(0))
                if len(data) < 30:
                    continue
                
                # Check if this is daily data by looking at timestamp gaps
                # Daily data should have ~86400000ms (24 hours) between entries
                gaps = []
                for i in range(min(5, len(data) - 1)):
                    gap = data[i+1][0] - data[i][0]
                    gaps.append(gap)
                
                avg_gap = sum(gaps) / len(gaps) if gaps else 0
                
                # Daily data: gap around 86400000ms (24 hours) ± 10%
                # Hourly data: gap around 3600000ms (1 hour)
                is_daily = 70000000 < avg_gap < 100000000  # ~19-28 hours
                
                # Score: prefer daily data with longest date range
                if is_daily:
                    date_range_days = (data[-1][0] - data[0][0]) / 86400000
                    score = date_range_days * 2  # Daily data worth more
                else:
                    score = len(data) * 0.1  # Hourly data worth less
                
                if score > best_score:
                    best_data = data
                    best_score = score
                    
            except:
                continue
        
        if not best_data or len(best_data) < 10:
            logger.warning(f"Could not find long-term daily data for {slug}")
            # Cache the "no data" result with explicit flag to avoid repeated fetches
            try:
                from .database import get_db
                db = get_db()
                cache_key = f"{futbin_id}_{self.platform}"
                db.db.longterm_cache.update_one(
                    {'cache_key': cache_key},
                    {'$set': {'cache_key': cache_key, 'no_data': True, 'cached_at': datetime.now()}},
                    upsert=True
                )
                logger.info(f"Cached {slug} as no-data for {max_cache_hours}h")
            except:
                pass
            return None
        
        prices = [d[1] for d in best_data]
        all_time_low = min(prices)
        all_time_high = max(prices)
        current = prices[-1]
        
        # Position in range: 0% = at floor, 100% = at peak
        price_range = all_time_high - all_time_low
        position_in_range = ((current - all_time_low) / price_range * 100) if price_range > 0 else 50
        
        # === RECENT RANGE (last 30 days) ===
        # This is more useful than all-time for buy decisions
        now_ms = datetime.now().timestamp() * 1000
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        recent_data = [d for d in best_data if d[0] > (now_ms - thirty_days_ms)]
        
        if len(recent_data) >= 5:
            recent_prices = [d[1] for d in recent_data]
            recent_low = min(recent_prices)
            recent_high = max(recent_prices)
            recent_range = recent_high - recent_low
            recent_position = ((current - recent_low) / recent_range * 100) if recent_range > 0 else 50
            
            # How much has price recovered from recent low? (as %)
            bounce_from_low = ((current - recent_low) / recent_low * 100) if recent_low > 0 else 0
        else:
            recent_low = all_time_low
            recent_high = all_time_high
            recent_position = position_in_range
            bounce_from_low = 0
        
        # Find floor date
        min_idx = prices.index(all_time_low)
        floor_timestamp = best_data[min_idx][0]
        floor_date = datetime.fromtimestamp(floor_timestamp / 1000)
        
        # Date range
        first_date = datetime.fromtimestamp(best_data[0][0] / 1000)
        last_date = datetime.fromtimestamp(best_data[-1][0] / 1000)
        
        logger.info(f"Found {len(best_data)} daily points for {slug}: low {all_time_low:,}, high {all_time_high:,}, position {position_in_range:.0f}%, recent_pos {recent_position:.0f}%, bounce {bounce_from_low:.0f}%")
        
        result = {
            'prices': best_data,
            'all_time_low': all_time_low,
            'all_time_high': all_time_high,
            'current': current,
            'position_in_range': position_in_range,
            'floor_date': floor_date,
            'first_date': first_date,
            'last_date': last_date,
            'data_points': len(best_data),
            'volatility_pct': (price_range / all_time_low * 100) if all_time_low > 0 else 0,
            # Recent range data (last 30 days)
            'recent_low': recent_low,
            'recent_high': recent_high,
            'recent_position': recent_position,  # 0% = at 30-day low, 100% = at 30-day high
            'bounce_from_low': bounce_from_low,  # How much has price recovered from recent low (%)
        }
        
        # Cache the result
        try:
            from .database import get_db
            db = get_db()
            
            cache_key = f"{futbin_id}_{self.platform}"
            db.db.longterm_cache.update_one(
                {'cache_key': cache_key},
                {
                    '$set': {
                        'cache_key': cache_key,
                        'futbin_id': futbin_id,
                        'platform': self.platform,
                        'data': result,
                        'cached_at': datetime.now()
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.debug(f"Failed to cache: {e}")
        
        return result
    
    def scrape_players(self, players: List[Dict]) -> List[PlayerPrice]:
        """
        Scrape prices for multiple players.
        
        Args:
            players: List of dicts with 'futbin_id' and 'slug' keys
        
        Returns:
            List of PlayerPrice objects for successful scrapes
        """
        results = []
        total = len(players)
        
        for i, player in enumerate(players, 1):
            futbin_id = player.get('futbin_id')
            slug = player.get('slug')
            
            if not futbin_id or not slug:
                logger.warning(f"Skipping player with missing data: {player}")
                continue
            
            logger.info(f"Progress: {i}/{total} - Scraping {slug}")
            
            try:
                price_data = self.get_player_prices(futbin_id, slug)
                if price_data:
                    results.append(price_data)
            except Exception as e:
                logger.error(f"Error scraping player {futbin_id} ({slug}): {e}")
        
        logger.info(f"Scraping complete: {len(results)}/{total} successful")
        return results


class FutbinSearchScraper:
    """Scraper for Futbin player search/database pages."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': Config.USER_AGENT,
        })
        self._last_request_time = 0
        self.delay = Config.SCRAPE_DELAY
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()
    
    def search_players(self, query: str = None, min_rating: int = None, 
                       page: int = 1) -> List[Dict]:
        """
        Search Futbin for players matching criteria.
        Returns basic player info (id, name, rating, etc.)
        
        Note: This scrapes the Futbin player database page.
        """
        url = f"{Config.FUTBIN_BASE_URL}/players"
        params = {'page': page}
        
        if query:
            params['search'] = query
        if min_rating:
            params['minrating'] = min_rating
        
        self._rate_limit()
        
        try:
            response = self.session.get(url, params=params, timeout=Config.REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Search request failed: {e}")
            return []
        
        soup = BeautifulSoup(response.text, 'lxml')
        players = []
        
        # Find player rows in the search results
        player_rows = soup.select('tr.player-row, tr[data-player-id]')
        
        for row in player_rows:
            try:
                player_id = row.get('data-player-id')
                if not player_id:
                    # Try to extract from link
                    link = row.select_one('a[href*="/player/"]')
                    if link:
                        href = link.get('href', '')
                        match = re.search(r'/player/(\d+)/', href)
                        if match:
                            player_id = match.group(1)
                
                if not player_id:
                    continue
                
                name_el = row.select_one('.player-name, td:nth-child(2)')
                rating_el = row.select_one('.rating, td:nth-child(1)')
                pos_el = row.select_one('.position, td:nth-child(3)')
                
                # Extract slug from player link
                link = row.select_one('a[href*="/player/"]')
                slug = None
                if link:
                    href = link.get('href', '')
                    match = re.search(r'/player/\d+/([^/]+)', href)
                    if match:
                        slug = match.group(1)
                
                players.append({
                    'futbin_id': int(player_id),
                    'name': name_el.text.strip() if name_el else None,
                    'slug': slug,
                    'rating': int(rating_el.text.strip()) if rating_el else None,
                    'position': pos_el.text.strip() if pos_el else None,
                })
            except Exception as e:
                logger.warning(f"Failed to parse player row: {e}")
                continue
        
        return players


# Convenience functions

def scrape_player(futbin_id: int, slug: str, platform: str = 'ps') -> Optional[PlayerPrice]:
    """Scrape a single player's price data."""
    scraper = FutbinScraper(platform=platform)
    return scraper.get_player_prices(futbin_id, slug)


def scrape_multiple_players(players: List[Dict], platform: str = 'ps') -> List[PlayerPrice]:
    """Scrape prices for a list of players."""
    scraper = FutbinScraper(platform=platform)
    return scraper.scrape_players(players)
