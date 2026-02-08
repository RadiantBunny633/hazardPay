# HazardPay

**FC 26 Ultimate Team Market Tracker**

An automated pipeline that scrapes EA FC 26 player prices from Futbin, stores historical data in MongoDB, and identifies investment opportunities based on price trends and patterns.

## Features

- **Futbin Scraper**: Fetches current prices, price ranges, and recent price history
- **Historical Backfill**: Imports 500 historical price points from Futbin sales pages
- **MongoDB Storage**: Stores historical price data for analysis (no complex setup)
- **Investment Signals**: Automatically detects:
  - Price drops (buying opportunities)
  - Price spikes (selling opportunities)
  - Momentum trends (up/down over multiple days)
  - Floor prices (minimal downside risk)
  - High volatility (flip opportunities)
- **Automated Scheduler**: Runs price fetches multiple times daily
- **Watchlist**: Track target buy/sell prices for specific players
- **Alerts System**: Get notified when signals are detected

## Installation

### Prerequisites

- Python 3.9+
- MongoDB (local or Atlas)
- pip

### Setup

1. **Clone and install dependencies:**

```bash
cd hazardPay
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Start MongoDB:**

```bash
# On macOS with Homebrew
brew services start mongodb-community

# Or use MongoDB Atlas (cloud) - update MONGODB_URI in config.py
```

3. **Initialize the database:**

```bash
python main.py db init
```

## Usage

### Quick Start

```bash
# Add a player with historical price backfill (500 price points!)
python main.py player add-url "https://www.futbin.com/26/player/21407/cruyff" --backfill

# Fetch current prices for all players
python main.py price fetch

# Run investment analysis
python main.py analyze run

# Start automated scheduler
python main.py schedule
```

### Player Management

```bash
# Add a player from Futbin URL
python main.py player add-url "https://www.futbin.com/26/player/21407/cruyff"

# Add with historical data backfill
python main.py player add-url "https://www.futbin.com/26/player/21407/cruyff" --backfill

# Bulk import from file (one URL per line)
python main.py player import-file players.txt --backfill

# List all tracked players
python main.py player list

# Remove a player (deactivate)
python main.py player remove <player_id>

# Permanently delete a player
python main.py player remove <player_id> --force
```

### Price Tracking

```bash
# Fetch prices for all active players
python main.py price fetch

# Fetch price for a specific player
python main.py price fetch --player-id <player_id>

# View price history with stats
python main.py price history <player_id>

# View more days of history
python main.py price history <player_id> --days 30
```

### Testing Scraper

```bash
# Test scraping a player (doesn't save to database)
python main.py scrape-test 21407 cruyff

# Test historical price fetching
python main.py history-test 21407 cruyff
```

### Investment Analysis

```bash
# Run full analysis
python main.py analyze run

# Save signals as alerts
python main.py analyze run --save

# Analyze specific player
python main.py analyze player <player_id>
```

### Watchlist

```bash
# Add to watchlist with target prices
python main.py watchlist add <player_id> --buy 500000 --sell 700000 --notes "Buy after TOTY"

# View watchlist
python main.py watchlist list

# Remove from watchlist
python main.py watchlist remove <player_id>
```

### Alerts

```bash
# View unread alerts
python main.py alerts list

# Clear all alerts
python main.py alerts clear

# Clear specific alert
python main.py alerts clear --alert-id 5
```

### Scheduler

```bash
# Start automated scheduler (runs in foreground)
python main.py schedule

# Run scrape/analysis immediately
python main.py run-now --job all
python main.py run-now --job prices
python main.py run-now --job analysis
```

### Testing

```bash
# Test scraping a player (doesn't save to DB)
python main.py scrape-test 21407 cruyff
```

### Platform Selection

All commands support `--platform` / `-p` to specify PlayStation or PC:

```bash
python main.py -p pc price fetch
python main.py -p ps analyze run
```

## Project Structure

```
hazardPay/
├── main.py                 # CLI entry point
├── config.py               # Configuration management
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── sql/
│   └── schema.sql         # Database schema
└── src/
    ├── __init__.py
    ├── database.py        # PostgreSQL operations
    ├── scraper.py         # Futbin scraper
    ├── player_manager.py  # Player CRUD + sync
    ├── analyzer.py        # Investment analysis
    └── scheduler.py       # Automated tasks
```

## Database Schema

- **players**: Player metadata (futbin_id, name, rating, position, etc.)
- **price_history**: Historical price snapshots
- **price_alerts**: Investment signals/notifications
- **watchlist**: Players you're actively monitoring
- **sales_history**: Individual sale records from Futbin

## Investment Signals Explained

| Signal             | Description              | Action                        |
| ------------------ | ------------------------ | ----------------------------- |
| `price_drop`       | Price fell >10% in 24h   | Consider buying               |
| `price_spike`      | Price rose >10% in 24h   | Consider selling / don't FOMO |
| `momentum_up`      | Trending up 3+ days      | Riding a wave                 |
| `momentum_down`    | Trending down 3+ days    | Wait to buy                   |
| `at_floor`         | Near price range minimum | Low risk buy                  |
| `high_volatility`  | High price variance      | Flip opportunity              |
| `watchlist_target` | Hit your target price    | Execute your plan             |

## Rate Limiting

The scraper respects Futbin with:

- 2-second delay between requests (configurable in `.env`)
- Session reuse for efficiency
- Graceful error handling

## Tips for Success

1. **Start small**: Track 10-20 players you know well
2. **Daily scrapes**: More data = better analysis
3. **Watch for events**: Content drops (TOTW, promos) cause price swings
4. **Use watchlists**: Set target prices and stick to your plan
5. **Price floors**: Buying near the minimum reduces downside risk

## Roadmap

- [ ] Web dashboard for visualization
- [ ] Telegram/Discord notifications
- [ ] Player search/discovery from Futbin
- [ ] Event calendar integration (content drops)
- [ ] Portfolio tracking (what you own)
- [ ] ROI calculations

## License

Personal use only. Not affiliated with EA or Futbin.

---

Built with 🐍 Python, 🐘 PostgreSQL, and ⚽ love for the game.
