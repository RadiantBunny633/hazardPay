#!/usr/bin/env python3
"""
HazardPay Scheduler
Runs price updates every 15 minutes in the background.
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Configuration
UPDATE_INTERVAL_MINUTES = 15
PROJECT_DIR = Path(__file__).parent.absolute()


def log(message: str):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def run_update():
    """Run the price update command."""
    try:
        log("Starting price update...")
        
        result = subprocess.run(
            [sys.executable, "main.py", "player", "update"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            # Count successful updates from output
            success_lines = [l for l in result.stdout.split('\n') if '✓' in l]
            log(f"✓ Update complete ({len(success_lines)} players)")
        else:
            log(f"✗ Update failed: {result.stderr[:200]}")
            
    except subprocess.TimeoutExpired:
        log("✗ Update timed out after 5 minutes")
    except Exception as e:
        log(f"✗ Error: {e}")


def main():
    """Main scheduler loop."""
    print("""
╔═══════════════════════════════════════════════════════════╗
║              HAZARDPAY SCHEDULER                          ║
║         Price updates every 15 minutes                    ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    log(f"Scheduler started - updates every {UPDATE_INTERVAL_MINUTES} minutes")
    log("Press Ctrl+C to stop\n")
    
    # Run immediately on start
    run_update()
    
    try:
        while True:
            # Calculate next run time
            next_run = datetime.now().timestamp() + (UPDATE_INTERVAL_MINUTES * 60)
            next_run_str = datetime.fromtimestamp(next_run).strftime("%H:%M:%S")
            log(f"Next update at {next_run_str}")
            
            # Sleep until next run
            time.sleep(UPDATE_INTERVAL_MINUTES * 60)
            
            # Run update
            run_update()
            
    except KeyboardInterrupt:
        log("\nScheduler stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
