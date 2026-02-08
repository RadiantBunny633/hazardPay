#!/usr/bin/env python3
"""Quick check for daily price data on Futbin."""
import requests
import re
import json
from datetime import datetime

url = 'https://www.futbin.com/26/player/20694/abily'
response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)

# Find all arrays that look like price data [[timestamp, price], ...]
# Look for the pattern with multiple entries
all_matches = list(re.finditer(r'\[\[1\d{12},\d+\](?:,\[1\d{12},\d+\])+\]', response.text))

print(f"Found {len(all_matches)} potential price arrays")

for i, match in enumerate(all_matches):
    data_str = match.group(0)
    try:
        data = json.loads(data_str)
        if len(data) > 10:  # Only care about substantial arrays
            prices = [d[1] for d in data]
            print(f"\n=== Array {i+1}: {len(data)} data points ===")
            print(f"ALL-TIME LOW:  {min(prices):,}")
            print(f"ALL-TIME HIGH: {max(prices):,}")
            print(f"CURRENT:       {prices[-1]:,}")
            
            # Calculate position in range
            low = min(prices)
            high = max(prices)
            current = prices[-1]
            if high > low:
                position = ((current - low) / (high - low)) * 100
                print(f"\nPosition in range: {position:.0f}%")
            
            # Date range
            first_date = datetime.fromtimestamp(data[0][0]/1000)
            last_date = datetime.fromtimestamp(data[-1][0]/1000)
            print(f"Date range: {first_date.strftime('%b %d, %Y')} to {last_date.strftime('%b %d, %Y')}")
            
            # Find when the floor occurred
            min_idx = prices.index(min(prices))
            floor_date = datetime.fromtimestamp(data[min_idx][0]/1000)
            print(f"Floor date: {floor_date.strftime('%b %d, %Y')} @ {min(prices):,}")
    except Exception as e:
        print(f"Array {i+1}: Error - {e}")
