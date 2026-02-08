#!/usr/bin/env python3
"""Debug velocity calculation"""

from src.database import get_db
from src.velocity import calculate_velocity
from datetime import datetime

db = get_db()

# Debug velocity for players showing 0.0%
players = db.get_all_players()

for player in players[:5]:
    print(f'=== {player["name"]} ===')
    history = db.get_price_history(player['id'], platform='ps', days=7, limit=200)
    print(f'History points: {len(history)}')
    
    if not history:
        print('No history!')
        continue
    
    current = history[0]['price']
    print(f'Current price: {current:,}')
    
    # Show recent prices
    print('Recent prices:')
    for h in history[:8]:
        ts = h.get('recorded_at')
        age = (datetime.now() - ts).total_seconds() / 3600
        print(f'  {age:.2f}h ago: {h["price"]:,}')
    
    # Calculate velocity
    v = calculate_velocity(history, current)
    if v:
        print(f'Velocity 1h: {v.velocity_1h}%/h')
        print(f'Velocity 6h: {v.velocity_6h}%/h')
        print(f'State: {v.state}')
        print(f'Description: {v.description}')
    else:
        print('Velocity returned None!')
    print()
