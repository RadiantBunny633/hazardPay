"""
HazardPay Configuration
Loads settings from environment variables with sensible defaults.
"""

import os
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


class Config:
    """Application configuration."""
    
    # MongoDB
    MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/hazardpay')
    DB_NAME = os.getenv('DB_NAME', 'hazardpay')
    
    # Scraping
    SCRAPE_DELAY = float(os.getenv('SCRAPE_DELAY', 2.0))  # seconds between requests
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 30))
    USER_AGENT = 'Mozilla/5.0'
    
    # Platform
    DEFAULT_PLATFORM = os.getenv('DEFAULT_PLATFORM', 'ps')  # 'ps' or 'pc'
    
    # Futbin base URL
    FUTBIN_BASE_URL = 'https://www.futbin.com/26'
