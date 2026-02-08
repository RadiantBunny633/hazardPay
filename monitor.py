#!/usr/bin/env python3
"""
HazardPay Monitor - Runs in background to track prices over time.

Usage:
    python monitor.py                    # Run once (for cron)
    python monitor.py --daemon           # Run continuously in background
    python monitor.py --daemon --interval 30   # Update every 30 minutes
"""

import argparse
import time
import logging
from datetime import datetime
from pathlib import Path

# Set up logging to file
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def update_prices(platform: str = 'ps') -> dict:
    """Update all player prices and return summary stats."""
    from src.player_manager import get_manager
    from src.database import get_db
    
    manager = get_manager(platform=platform)
    db = get_db()
    
    players = manager.get_active_players()
    updated = 0
    failed = 0
    
    for player in players:
        try:
            price = manager.fetch_price(player['id'])
            if price:
                updated += 1
                logger.debug(f"  {player['name']}: {price:,}")
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Failed to update {player['name']}: {e}")
            failed += 1
        
        # Small delay between requests to be nice to Futbin
        time.sleep(1)
    
    return {
        'total': len(players),
        'updated': updated,
        'failed': failed,
        'timestamp': datetime.now()
    }


def check_alerts(platform: str = 'ps') -> list:
    """Check for any triggered alerts."""
    try:
        from src.alert_manager import get_alert_manager
        alert_mgr = get_alert_manager(platform=platform)
        triggered = alert_mgr.check_alerts()
        return triggered
    except ImportError:
        # Alert manager not implemented yet
        return []
    except Exception as e:
        logger.debug(f"Alert check skipped: {e}")
        return []


def analyze_market(platform: str = 'ps') -> dict:
    """Run market pulse analysis."""
    from src.market_pulse import MarketPulseAnalyzer
    
    analyzer = MarketPulseAnalyzer(platform=platform)
    pulse = analyzer.get_pulse(fetch_fresh=False)  # Use cache to be fast
    
    if not pulse:
        return None
    
    return {
        'overall_status': pulse.status,
        'avg_position': pulse.avg_position_in_range,
        'pct_at_lows': pulse.pct_at_lows,
        'pct_at_highs': pulse.pct_at_highs,
        'recommendation': pulse.summary
    }


def find_buy_opportunities(platform: str = 'ps', top_n: int = 5) -> list:
    """Find the best buy opportunities based on V3 smart signals."""
    from src.smart_signals import SmartSignals
    
    signals = SmartSignals(platform=platform)
    opportunities = signals.scan_buy_opportunities(min_score=55)
    
    results = []
    for opp in opportunities[:top_n]:
        # Extract buy readiness from reasons (V3 adds ✓ READY reasons)
        ready_status = "WAIT"
        for reason in (opp.reasons or []):
            if reason.startswith("✓"):
                ready_status = "READY"
                break
            elif reason.startswith("⏳"):
                ready_status = "ALMOST"
                break
        
        results.append({
            'name': opp.player_name,
            'price': opp.current_price,
            'score': opp.score,
            'signal': opp.signal_type,
            'confidence': getattr(opp, 'confidence', 'MEDIUM'),
            'ready': ready_status,
            'reasons': opp.reasons[:2] if opp.reasons else []
        })
    
    return results


def run_cycle(platform: str = 'ps', analyze: bool = True):
    """Run one complete monitoring cycle."""
    logger.info("=" * 60)
    logger.info(f"Starting monitoring cycle at {datetime.now()}")
    logger.info("=" * 60)
    
    # 1. Update prices
    logger.info("Updating prices...")
    stats = update_prices(platform)
    logger.info(f"Prices updated: {stats['updated']}/{stats['total']} success, {stats['failed']} failed")
    
    # 2. Check alerts
    logger.info("Checking alerts...")
    triggered = check_alerts(platform)
    if triggered:
        logger.warning(f"🚨 {len(triggered)} ALERTS TRIGGERED!")
        for alert in triggered:
            logger.warning(f"  → {alert['player_name']}: {alert['type']} at {alert['current_price']:,}")
    else:
        logger.info("No alerts triggered")
    
    # 3. Market analysis (optional, slower)
    if analyze:
        logger.info("Analyzing market...")
        try:
            market = analyze_market(platform)
            logger.info(f"Market Status: {market['overall_status']}")
            logger.info(f"  Avg Position: {market['avg_position']:.1f}%")
            logger.info(f"  At Lows: {market['pct_at_lows']:.0f}% | At Highs: {market['pct_at_highs']:.0f}%")
            logger.info(f"  Recommendation: {market['recommendation']}")
        except Exception as e:
            logger.error(f"Market analysis failed: {e}")
        
        # 4. Find buy opportunities (V3 with buy readiness)
        logger.info("Scanning for buy opportunities...")
        try:
            buys = find_buy_opportunities(platform)
            if buys:
                logger.info(f"🎯 TOP {len(buys)} BUY OPPORTUNITIES:")
                for b in buys:
                    ready_icon = "✓" if b['ready'] == "READY" else "⏳" if b['ready'] == "ALMOST" else "⏸"
                    reason_str = ' | '.join(b['reasons']) if b['reasons'] else ''
                    logger.info(f"  {ready_icon} {b['name']}: {b['price']:,} coins | Score: {b['score']}/100 | {b['signal']} | {b['confidence']} conf")
                    if reason_str:
                        logger.info(f"      {reason_str}")
            else:
                logger.info("No strong buy opportunities found (score >= 55)")
        except Exception as e:
            logger.error(f"Buy scan failed: {e}")
    
    logger.info(f"Cycle complete at {datetime.now()}")
    logger.info("")
    
    return stats


def daemon_mode(platform: str, interval_minutes: int, analyze: bool):
    """Run continuously in background."""
    logger.info(f"Starting daemon mode - updating every {interval_minutes} minutes")
    logger.info("Press Ctrl+C to stop")
    
    try:
        while True:
            run_cycle(platform, analyze=analyze)
            
            logger.info(f"Sleeping for {interval_minutes} minutes...")
            time.sleep(interval_minutes * 60)
            
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")


def main():
    parser = argparse.ArgumentParser(description="HazardPay Background Monitor")
    parser.add_argument('--platform', '-p', default='ps', choices=['ps', 'pc'],
                        help='Platform (ps or pc)')
    parser.add_argument('--daemon', '-d', action='store_true',
                        help='Run continuously in background')
    parser.add_argument('--interval', '-i', type=int, default=60,
                        help='Minutes between updates in daemon mode (default: 60)')
    parser.add_argument('--no-analyze', action='store_true',
                        help='Skip market analysis (faster)')
    
    args = parser.parse_args()
    
    if args.daemon:
        daemon_mode(args.platform, args.interval, not args.no_analyze)
    else:
        run_cycle(args.platform, not args.no_analyze)


if __name__ == "__main__":
    main()
