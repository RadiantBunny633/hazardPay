#!/usr/bin/env python3
"""Debug Saka data"""

from src.database import get_db
from src.scraper import FutbinScraper

db = get_db()

# Clear cache for Saka to get fresh data with new fields
print("Clearing cache for fresh data...")
db.db.longterm_cache.delete_many({})

scraper = FutbinScraper()

# Find Saka
players = db.get_all_players()
saka = next((p for p in players if 'Saka' in p['name']), None)

if saka:
    print(f'=== {saka["name"]} ===')
    print(f'Futbin ID: {saka["futbin_id"]}')
    slug = saka.get('slug', saka['name'].lower().replace(' ', '-'))
    print(f'Slug: {slug}')
    
    # Get long-term data using correct method
    longterm = scraper.get_longterm_daily_prices(saka['futbin_id'], slug)
    if longterm:
        print(f'Long-term data:')
        print(f'  ATL: {longterm.get("all_time_low"):,}')
        print(f'  ATH: {longterm.get("all_time_high"):,}')
        print(f'  Position (all-time): {longterm.get("position_in_range"):.0f}%')
        print(f'')
        print(f'  30-day Low: {longterm.get("recent_low"):,}')
        print(f'  30-day High: {longterm.get("recent_high"):,}')
        print(f'  Position (30-day): {longterm.get("recent_position"):.0f}%')
        print(f'  Bounce from low: {longterm.get("bounce_from_low"):.0f}%')
        print(f'')
        print(f'  Data points: {longterm.get("data_points")}')
    else:
        print('No long-term data!')
else:
    print('Saka not found!')
