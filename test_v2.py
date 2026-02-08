#!/usr/bin/env python3
"""Test V2 Smart Signals"""

from src.smart_signals import SmartSignals
from src.database import get_db
from collections import Counter

def main():
    ss = SmartSignals()
    db = get_db()
    
    print('=== V2 BUY OPPORTUNITIES (Score >= 60) ===')
    print()
    
    opportunities = ss.scan_buy_opportunities(min_score=60)
    
    if not opportunities:
        print('No strong buy opportunities right now.')
        print('This is GOOD - the system is being selective!')
        print()
    else:
        for signal in opportunities[:10]:
            print(f'{signal.player_name}: {signal.score}/100')
            if signal.velocity:
                print(f'  Momentum: {signal.velocity.description}')
            print(f'  Price: {signal.current_price:,} coins')
            print(f'  Reasons: {signal.reasons[:2]}')
            print()
    
    print('=== SCORE DISTRIBUTION ===')
    all_players = db.get_all_players()
    scores = []
    for p in all_players:
        s = ss.get_buy_score(p['id'])
        if s:
            scores.append((p['name'], s.score, s.signal_type))
    
    type_counts = Counter(s[2] for s in scores)
    print(f'AVOID (0-39):     {type_counts.get("AVOID", 0)}')
    print(f'WAIT (0-39):      {type_counts.get("WAIT", 0)}')
    print(f'HOLD (40-59):     {type_counts.get("HOLD", 0)}')
    print(f'BUY (60-79):      {type_counts.get("BUY", 0)}')
    print(f'STRONG_BUY (80+): {type_counts.get("STRONG_BUY", 0)}')
    print()
    
    # Show score histogram
    print('=== SCORE HISTOGRAM ===')
    buckets = [
        ('0-19', 0), ('20-39', 0), ('40-59', 0), ('60-79', 0), ('80-100', 0)
    ]
    bucket_counts = {b[0]: 0 for b in buckets}
    
    for _, score, _ in scores:
        if score < 20:
            bucket_counts['0-19'] += 1
        elif score < 40:
            bucket_counts['20-39'] += 1
        elif score < 60:
            bucket_counts['40-59'] += 1
        elif score < 80:
            bucket_counts['60-79'] += 1
        else:
            bucket_counts['80-100'] += 1
    
    max_count = max(bucket_counts.values()) if bucket_counts.values() else 1
    bar_width = 30  # Max bar width in characters
    
    for label in ['0-19', '20-39', '40-59', '60-79', '80-100']:
        count = bucket_counts[label]
        bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0
        bar = '█' * bar_len
        print(f'{label:>6}: {bar:<{bar_width}} ({count:>2})')

if __name__ == '__main__':
    main()
