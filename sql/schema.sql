-- HazardPay Database Schema
-- PostgreSQL schema for FC 26 market tracking

-- Players table - stores player metadata
CREATE TABLE IF NOT EXISTS players (
    id SERIAL PRIMARY KEY,
    futbin_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100),  -- URL-friendly name (e.g., 'cruyff', 'ribery')
    rating INTEGER,
    position VARCHAR(10),
    version VARCHAR(50),  -- 'gold', 'icon', 'heroes', 'toty', etc.
    league VARCHAR(100),
    nation VARCHAR(100),
    club VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,  -- Whether to track this player
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Price history table - stores historical price snapshots
CREATE TABLE IF NOT EXISTS price_history (
    id SERIAL PRIMARY KEY,
    player_id INTEGER REFERENCES players(id) ON DELETE CASCADE,
    price INTEGER NOT NULL,
    platform VARCHAR(10) DEFAULT 'ps',  -- 'ps' or 'pc'
    price_min INTEGER,  -- Price range minimum
    price_max INTEGER,  -- Price range maximum
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- Price alerts table - track investment signals
CREATE TABLE IF NOT EXISTS price_alerts (
    id SERIAL PRIMARY KEY,
    player_id INTEGER REFERENCES players(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,  -- 'price_drop', 'momentum_up', 'at_floor', etc.
    message TEXT,
    price_at_alert INTEGER,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Watchlist table - players you're actively monitoring for investment
CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    player_id INTEGER REFERENCES players(id) ON DELETE CASCADE,
    target_buy_price INTEGER,  -- Price you want to buy at
    target_sell_price INTEGER,  -- Price you want to sell at
    notes TEXT,
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(player_id)
);

-- Sales history table - individual sales from Futbin
CREATE TABLE IF NOT EXISTS sales_history (
    id SERIAL PRIMARY KEY,
    player_id INTEGER REFERENCES players(id) ON DELETE CASCADE,
    sale_timestamp TIMESTAMP,
    listed_price INTEGER,
    sold_price INTEGER,
    ea_tax INTEGER,
    net_price INTEGER,
    sale_type VARCHAR(20),  -- 'Buy Now', 'Auction', etc.
    platform VARCHAR(10) DEFAULT 'ps',
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_price_history_player_date 
    ON price_history(player_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_price_history_platform 
    ON price_history(platform);

CREATE INDEX IF NOT EXISTS idx_price_alerts_unread 
    ON price_alerts(is_read, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_players_active 
    ON players(is_active);

CREATE INDEX IF NOT EXISTS idx_players_futbin_id 
    ON players(futbin_id);

CREATE INDEX IF NOT EXISTS idx_sales_history_player_date 
    ON sales_history(player_id, sale_timestamp DESC);

-- Useful views

-- Latest prices for all active players
CREATE OR REPLACE VIEW latest_prices AS
SELECT DISTINCT ON (ph.player_id, ph.platform)
    p.id,
    p.futbin_id,
    p.name,
    p.rating,
    p.position,
    ph.price,
    ph.platform,
    ph.recorded_at
FROM players p
JOIN price_history ph ON p.id = ph.player_id
WHERE p.is_active = TRUE
ORDER BY ph.player_id, ph.platform, ph.recorded_at DESC;

-- Price change analysis (last 24 hours vs previous 24 hours)
CREATE OR REPLACE VIEW price_changes_24h AS
WITH current_prices AS (
    SELECT DISTINCT ON (player_id, platform)
        player_id,
        platform,
        price as current_price,
        recorded_at
    FROM price_history
    WHERE recorded_at >= NOW() - INTERVAL '24 hours'
    ORDER BY player_id, platform, recorded_at DESC
),
previous_prices AS (
    SELECT DISTINCT ON (player_id, platform)
        player_id,
        platform,
        price as previous_price,
        recorded_at
    FROM price_history
    WHERE recorded_at >= NOW() - INTERVAL '48 hours'
      AND recorded_at < NOW() - INTERVAL '24 hours'
    ORDER BY player_id, platform, recorded_at DESC
)
SELECT 
    p.id,
    p.name,
    p.rating,
    cp.platform,
    cp.current_price,
    pp.previous_price,
    cp.current_price - pp.previous_price as price_change,
    ROUND(((cp.current_price - pp.previous_price)::numeric / pp.previous_price) * 100, 2) as pct_change
FROM players p
JOIN current_prices cp ON p.id = cp.player_id
LEFT JOIN previous_prices pp ON p.id = pp.player_id AND cp.platform = pp.platform
WHERE p.is_active = TRUE
ORDER BY pct_change ASC NULLS LAST;
