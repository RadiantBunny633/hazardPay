"""
Scheduler Module for HazardPay.
Handles automated daily price scraping and analysis.
"""

import logging
from datetime import datetime
from typing import Callable, Optional
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .player_manager import PlayerManager, get_manager
from .analyzer import InvestmentAnalyzer, get_analyzer
from .database import get_db

logger = logging.getLogger(__name__)


class HazardPayScheduler:
    """Handles scheduled tasks for price scraping and analysis."""
    
    def __init__(self, platform: str = 'ps', blocking: bool = True):
        self.platform = platform
        self.manager = get_manager(platform=platform)
        self.analyzer = get_analyzer(platform=platform)
        self.db = get_db()
        
        # Use blocking scheduler for standalone script, background for integration
        if blocking:
            self.scheduler = BlockingScheduler()
        else:
            self.scheduler = BackgroundScheduler()
        
        self._setup_default_jobs()
    
    def _setup_default_jobs(self):
        """Set up default scheduled jobs."""
        # Daily price scrape - runs at 6 AM, 12 PM, 6 PM, 12 AM
        self.scheduler.add_job(
            self.job_fetch_prices,
            CronTrigger(hour='0,6,12,18', minute=0),
            id='fetch_prices',
            name='Fetch all player prices',
            replace_existing=True
        )
        
        # Daily analysis - runs at 7 AM (after morning scrape)
        self.scheduler.add_job(
            self.job_run_analysis,
            CronTrigger(hour=7, minute=0),
            id='run_analysis',
            name='Run investment analysis',
            replace_existing=True
        )
    
    def job_fetch_prices(self):
        """Job: Fetch prices for all active players."""
        logger.info("=" * 50)
        logger.info(f"Starting scheduled price fetch at {datetime.now()}")
        
        try:
            result = self.manager.fetch_all_prices()
            logger.info(f"Price fetch complete: {result['success']} success, {result['failed']} failed")
        except Exception as e:
            logger.error(f"Price fetch failed: {e}")
        
        logger.info("=" * 50)
    
    def job_run_analysis(self):
        """Job: Run full investment analysis and save alerts."""
        logger.info("=" * 50)
        logger.info(f"Starting scheduled analysis at {datetime.now()}")
        
        try:
            signals = self.analyzer.run_full_analysis()
            
            if signals:
                saved = self.analyzer.save_signals_as_alerts(signals)
                logger.info(f"Analysis complete: {len(signals)} signals found, {saved} saved as alerts")
                
                # Log high-severity signals
                high_signals = [s for s in signals if s.severity == 'high']
                for signal in high_signals:
                    logger.warning(f"HIGH ALERT: {signal.player_name} - {signal.message}")
            else:
                logger.info("Analysis complete: No significant signals found")
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
        
        logger.info("=" * 50)
    
    def add_custom_job(
        self,
        func: Callable,
        trigger: str = 'cron',
        job_id: str = None,
        **trigger_args
    ):
        """
        Add a custom scheduled job.
        
        Args:
            func: Function to execute
            trigger: 'cron' or 'interval'
            job_id: Unique job identifier
            **trigger_args: Arguments for the trigger (hour, minute, seconds, etc.)
        """
        if trigger == 'cron':
            trigger_obj = CronTrigger(**trigger_args)
        elif trigger == 'interval':
            trigger_obj = IntervalTrigger(**trigger_args)
        else:
            raise ValueError(f"Unknown trigger type: {trigger}")
        
        self.scheduler.add_job(
            func,
            trigger_obj,
            id=job_id,
            replace_existing=True
        )
        logger.info(f"Added custom job: {job_id}")
    
    def remove_job(self, job_id: str):
        """Remove a scheduled job."""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job: {job_id}")
        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")
    
    def list_jobs(self):
        """List all scheduled jobs."""
        jobs = self.scheduler.get_jobs()
        return [
            {
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time,
                'trigger': str(job.trigger)
            }
            for job in jobs
        ]
    
    def run_now(self, job_type: str = 'all'):
        """
        Run jobs immediately (for testing/manual trigger).
        
        Args:
            job_type: 'prices', 'analysis', or 'all'
        """
        if job_type in ('prices', 'all'):
            self.job_fetch_prices()
        
        if job_type in ('analysis', 'all'):
            self.job_run_analysis()
    
    def start(self):
        """Start the scheduler."""
        logger.info("Starting HazardPay scheduler...")
        logger.info(f"Scheduled jobs: {len(self.scheduler.get_jobs())}")
        
        for job in self.scheduler.get_jobs():
            logger.info(f"  - {job.name}: next run at {job.next_run_time}")
        
        try:
            self.scheduler.start()
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            self.stop()
    
    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def run_scheduler(platform: str = 'ps'):
    """Run the scheduler as a standalone process."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    scheduler = HazardPayScheduler(platform=platform, blocking=True)
    scheduler.start()


if __name__ == '__main__':
    run_scheduler()
