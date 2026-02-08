#!/usr/bin/env python3
"""
HazardPay CLI - FC 26 Ultimate Team Market Tracker

Main entry point for the application.
"""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config

console = Console()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """Print the HazardPay banner."""
    banner = """
██╗  ██╗ █████╗ ███████╗ █████╗ ██████╗ ██████╗ ██████╗  █████╗ ██╗   ██╗
██║  ██║██╔══██╗╚══███╔╝██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗╚██╗ ██╔╝
███████║███████║  ███╔╝ ███████║██████╔╝██║  ██║██████╔╝███████║ ╚████╔╝ 
██╔══██║██╔══██║ ███╔╝  ██╔══██║██╔══██╗██║  ██║██╔═══╝ ██╔══██║  ╚██╔╝  
██║  ██║██║  ██║███████╗██║  ██║██║  ██║██████╔╝██║     ██║  ██║   ██║   
╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝     ╚═╝  ╚═╝   ╚═╝   
    """
    console.print(banner, style="bold cyan")
    console.print("FC 26 Ultimate Team Market Tracker\n", style="dim")


@click.group()
@click.option('--console', '-c', 'platform', default='ps', type=click.Choice(['ps', 'pc']),
              help='Console/platform to use (ps or pc)')
@click.pass_context
def cli(ctx, platform):
    """HazardPay - FC 26 Ultimate Team Market Tracker"""
    ctx.ensure_object(dict)
    ctx.obj['platform'] = platform


# ========== Database Commands ==========

@cli.group()
def db():
    """Database management commands."""
    pass


@db.command('init')
def db_init():
    """Initialize the database schema."""
    from src.database import get_db
    
    console.print("Initializing database schema...", style="yellow")
    
    try:
        db = get_db()
        db.init_schema()
        console.print("✓ Database schema initialized successfully!", style="bold green")
    except Exception as e:
        console.print(f"✗ Failed to initialize database: {e}", style="bold red")
        raise click.Abort()


@db.command('stats')
def db_stats():
    """Show database statistics."""
    from src.database import get_db
    
    db = get_db()
    
    # Get collection stats
    players_count = db.db.players.count_documents({})
    prices_count = db.db.price_history.count_documents({})
    alerts_count = db.db.alerts.count_documents({})
    watchlist_count = db.db.watchlist.count_documents({})
    
    # Get database size
    stats = db.db.command('dbStats')
    size_mb = stats['dataSize'] / (1024 * 1024)
    storage_mb = stats['storageSize'] / (1024 * 1024)
    
    console.print("\n[bold]📊 Database Statistics[/bold]\n")
    
    table = Table(box=box.SIMPLE)
    table.add_column("Collection", style="cyan")
    table.add_column("Documents", justify="right")
    
    table.add_row("Players", f"{players_count:,}")
    table.add_row("Price Records", f"{prices_count:,}")
    table.add_row("Alerts", f"{alerts_count:,}")
    table.add_row("Watchlist", f"{watchlist_count:,}")
    
    console.print(table)
    console.print(f"\n[bold]Storage:[/bold] {size_mb:.2f} MB data ({storage_mb:.2f} MB on disk)")
    
    # Estimate growth
    if prices_count > 0 and players_count > 0:
        avg_per_player = prices_count / players_count
        daily_estimate = players_count * 24  # assuming hourly fetches
        yearly_mb = (daily_estimate * 365 * 150) / (1024 * 1024)  # ~150 bytes per record
        console.print(f"[dim]Estimated yearly growth: ~{yearly_mb:.0f} MB[/dim]")


# ========== Player Commands ==========

@cli.group()
def player():
    """Player management commands."""
    pass


@player.command('add')
@click.argument('futbin_id', type=int)
@click.argument('name')
@click.option('--slug', '-s', default=None, help='URL slug (auto-generated if not provided)')
@click.option('--rating', '-r', type=int, default=None, help='Player rating')
@click.option('--position', default=None, help='Player position')
@click.option('--no-price', is_flag=True, help="Don't fetch initial price")
@click.pass_context
def player_add(ctx, futbin_id, name, slug, rating, position, no_price):
    """Add a player to track."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    with console.status(f"Adding player {name}..."):
        result = manager.add_player(
            futbin_id=futbin_id,
            name=name,
            slug=slug,
            rating=rating,
            position=position,
            fetch_initial_price=not no_price
        )
    
    if result:
        console.print(f"✓ Added [bold]{result['name']}[/bold] (ID: {result['id']})", style="green")
        if result.get('current_price'):
            console.print(f"  Current price: [cyan]{result['current_price']:,}[/cyan] coins")
    else:
        console.print("✗ Failed to add player", style="bold red")


@player.command('add-url')
@click.argument('url')
@click.option('--backfill', '-b', is_flag=True, help='Backfill historical prices from Futbin')
@click.pass_context
def player_add_url(ctx, url, backfill):
    """Add a player from a Futbin URL."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    status_msg = "Adding player and fetching history..." if backfill else "Adding player from URL..."
    with console.status(status_msg):
        result = manager.add_player_by_url(url, backfill_history=backfill)
    
    if result:
        console.print(f"✓ Added [bold]{result['name']}[/bold]", style="green")
        if result.get('current_price'):
            console.print(f"  Current price: [cyan]{result['current_price']:,}[/cyan] coins")
        if result.get('history_count', 0) > 0:
            console.print(f"  Backfilled: [cyan]{result['history_count']:,}[/cyan] historical prices")
    else:
        console.print("✗ Failed to add player. Check the URL format.", style="bold red")


@player.command('import')
@click.argument('file_path', type=click.Path(exists=True))
@click.option('--skip-existing', '-s', is_flag=True, help='Skip already tracked players')
@click.pass_context
def player_import(ctx, file_path, skip_existing):
    """
    Bulk import players from a file.
    
    File should have one Futbin URL per line. Lines starting with # are ignored.
    """
    from src.player_manager import get_manager
    from src.database import get_db
    import time
    
    manager = get_manager(platform=ctx.obj['platform'])
    db = get_db()
    
    # Read URLs from file
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    urls = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            urls.append(line)
    
    if not urls:
        console.print("No URLs found in file", style="yellow")
        return
    
    console.print(f"Found [bold]{len(urls)}[/bold] URLs to import\n")
    
    added = 0
    skipped = 0
    failed = 0
    
    for i, url in enumerate(urls, 1):
        try:
            # Check if already exists
            if skip_existing:
                # Extract futbin_id from URL
                import re
                match = re.search(r'/player/(\d+)/', url)
                if match:
                    futbin_id = int(match.group(1))
                    existing = db.db.players.find_one({'futbin_id': futbin_id})
                    if existing:
                        console.print(f"[{i}/{len(urls)}] [dim]Skipped:[/dim] {existing['name']} (already tracked)")
                        skipped += 1
                        continue
            
            result = manager.add_player_by_url(url, backfill_history=False)
            
            if result:
                console.print(f"[{i}/{len(urls)}] [green]Added:[/green] {result['name']} @ {result.get('current_price', 0):,}")
                added += 1
            else:
                console.print(f"[{i}/{len(urls)}] [red]Failed:[/red] {url}")
                failed += 1
            
            # Rate limit to avoid bot detection
            time.sleep(1.5)
            
        except Exception as e:
            console.print(f"[{i}/{len(urls)}] [red]Error:[/red] {url} - {e}")
            failed += 1
    
    console.print(f"\n[bold]Import complete![/bold]")
    console.print(f"  Added:   [green]{added}[/green]")
    console.print(f"  Skipped: [yellow]{skipped}[/yellow]")
    console.print(f"  Failed:  [red]{failed}[/red]")


def get_buy_color(position: float) -> str:
    """
    Get a color based on position in range (0-100).
    Low position = green (good buy), High position = red (bad buy)
    Uses RGB interpolation for smooth gradient.
    """
    # Clamp position to 0-100
    position = max(0, min(100, position))
    
    if position <= 50:
        # Green to Yellow: 0% = bright green, 50% = yellow/neutral
        # Intensity: deeper green the lower the position
        ratio = position / 50  # 0 at position 0, 1 at position 50
        r = int(100 + ratio * 155)  # 100 -> 255
        g = int(255 - ratio * 55)   # 255 -> 200
        b = int(50)                  # stays low
    else:
        # Yellow to Red: 50% = yellow, 100% = bright red
        ratio = (position - 50) / 50  # 0 at position 50, 1 at position 100
        r = 255                       # stays high
        g = int(200 - ratio * 200)    # 200 -> 0
        b = int(50 - ratio * 50)      # 50 -> 0
    
    return f"#{r:02x}{g:02x}{b:02x}"


def get_change_color(pct_change: float) -> str:
    """
    Get a color for price change percentage.
    Positive = green (price up), Negative = red (price down)
    Intensity scales with magnitude (capped at ±20%)
    """
    # Cap at ±20% for color intensity
    magnitude = min(abs(pct_change), 20) / 20  # 0 to 1
    
    if pct_change > 0:
        # Price went up - green shades
        r = int(50 + (1 - magnitude) * 150)   # 50-200
        g = int(150 + magnitude * 105)         # 150-255
        b = int(50 + (1 - magnitude) * 100)   # 50-150
    elif pct_change < 0:
        # Price went down - red shades
        r = int(180 + magnitude * 75)          # 180-255
        g = int(100 - magnitude * 100)         # 100-0
        b = int(100 - magnitude * 100)         # 100-0
    else:
        return "dim"
    
    return f"#{r:02x}{g:02x}{b:02x}"


@player.command('list')
@click.option('--all', '-a', 'show_all', is_flag=True, help='Show all players (including inactive)')
@click.pass_context
def player_list(ctx, show_all):
    """List tracked players with price changes."""
    from src.player_manager import get_manager
    from src.database import get_db
    from datetime import datetime, timedelta
    
    manager = get_manager(platform=ctx.obj['platform'])
    db = get_db()
    platform = ctx.obj['platform']
    
    if show_all:
        players = manager.get_all_players()
    else:
        players = manager.get_active_players()
    
    if not players:
        console.print("No players found. Use 'hazardpay player add' to add some!", style="yellow")
        return
    
    table = Table(title="Tracked Players", box=box.ROUNDED)
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Name", style="bold")
    table.add_column("Price", justify="right", style="cyan")
    table.add_column("Position", justify="center")  # 0-100% in range
    table.add_column("24H Δ", justify="right")
    table.add_column("7D Δ", justify="right")
    table.add_column("Floor", justify="right", style="dim")
    
    for p in players:
        # Get current price from latest DB entry
        latest = db.get_latest_price(p['id'], platform=platform)
        price_str = f"{latest['price']:,}" if latest else "-"
        current_price = latest['price'] if latest else 0
        
        # Get cached long-term data (from Futbin)
        cache_key = f"{p['futbin_id']}_{platform}"
        cached = db.db.longterm_cache.find_one({'cache_key': cache_key})
        
        position_str = "-"
        floor_str = "-"
        change_24h = "-"
        change_7d = "-"
        
        if cached and cached.get('data'):
            data = cached['data']
            prices = data.get('prices', [])
            
            # Position in range with gradient color
            position = data.get('position_in_range', 50)
            color = get_buy_color(position)
            position_str = f"[{color}]{position:.0f}%[/{color}]"
            
            # Floor
            floor = data.get('all_time_low', 0)
            floor_str = f"{floor:,}" if floor else "-"
            
            # Calculate 24H and 7D changes from Futbin historical data
            if prices and len(prices) >= 2:
                now_ts = prices[-1][0]
                current = prices[-1][1]
                
                # Find price ~24h ago
                target_24h = now_ts - (24 * 60 * 60 * 1000)
                price_24h = None
                for ts, price in reversed(prices):
                    if ts <= target_24h:
                        price_24h = price
                        break
                
                if price_24h:
                    pct = ((current - price_24h) / price_24h) * 100
                    color = get_change_color(pct)
                    sign = "+" if pct > 0 else ""
                    change_24h = f"[{color}]{sign}{pct:.1f}%[/{color}]"
                
                # Find price ~7d ago
                target_7d = now_ts - (7 * 24 * 60 * 60 * 1000)
                price_7d = None
                for ts, price in reversed(prices):
                    if ts <= target_7d:
                        price_7d = price
                        break
                
                if price_7d:
                    pct = ((current - price_7d) / price_7d) * 100
                    color = get_change_color(pct)
                    sign = "+" if pct > 0 else ""
                    change_7d = f"[{color}]{sign}{pct:.1f}%[/{color}]"
        
        table.add_row(
            str(p['id'])[:8],
            p['name'],
            price_str,
            position_str,
            change_24h,
            change_7d,
            floor_str
        )
    
    console.print(table)
    console.print("\n[dim]Position = where price is in all-time range (0% = floor, 100% = peak)[/dim]")
    console.print("[dim]🟢 Deep green = great buy | 🟡 Yellow = neutral | 🔴 Deep red = avoid/sell[/dim]")
    console.print("[dim]Changes calculated from Futbin historical data[/dim]")


@player.command('update')
@click.argument('player_id', required=False)
@click.pass_context
def player_update(ctx, player_id):
    """Refresh prices for one or all players."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    if player_id:
        # Update single player
        player = manager.get_player(player_id=player_id)
        if not player:
            console.print(f"Player {player_id} not found", style="red")
            return
        
        console.print(f"Updating {player['name']}...", style="yellow")
        price = manager.fetch_price(player_id)
        if price:
            console.print(f"✓ {player['name']}: {price:,} coins", style="green")
        else:
            console.print(f"✗ Failed to fetch price", style="red")
    else:
        # Update all players
        players = manager.get_all_players()
        if not players:
            console.print("No players to update", style="yellow")
            return
        
        console.print(f"Updating {len(players)} players...\n", style="yellow")
        
        success = 0
        for p in players:
            try:
                price = manager.fetch_price(p['id'])
                if price:
                    console.print(f"  ✓ {p['name']}: {price:,}", style="green")
                    success += 1
                else:
                    console.print(f"  ✗ {p['name']}: failed", style="red")
            except Exception as e:
                console.print(f"  ✗ {p['name']}: {e}", style="red")
        
        console.print(f"\n✓ Updated {success}/{len(players)} players", style="bold green")


@player.command('remove')
@click.argument('player_id', type=int)
@click.option('--force', '-f', is_flag=True, help='Delete permanently (otherwise just deactivates)')
@click.pass_context
def player_remove(ctx, player_id, force):
    """Remove/deactivate a player."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    if force:
        if click.confirm(f"Permanently delete player {player_id} and all their data?"):
            if manager.delete_player(player_id):
                console.print(f"✓ Deleted player {player_id}", style="green")
            else:
                console.print("✗ Failed to delete player", style="red")
    else:
        if manager.deactivate_player(player_id):
            console.print(f"✓ Deactivated player {player_id}", style="green")
        else:
            console.print("✗ Failed to deactivate player", style="red")


@player.command('import-file')
@click.argument('filepath', type=click.Path(exists=True))
@click.option('--backfill', '-b', is_flag=True, help='Backfill historical prices for each player')
@click.option('--delay', '-d', default=2.0, help='Delay between requests (seconds)')
@click.pass_context
def player_import_file(ctx, filepath, backfill, delay):
    """Import players from a file (one Futbin URL per line)."""
    from src.player_manager import get_manager
    import time
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    with open(filepath, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    if not urls:
        console.print("No URLs found in file", style="yellow")
        return
    
    console.print(f"Found [bold]{len(urls)}[/bold] player URLs to import", style="cyan")
    
    added = 0
    failed = 0
    
    for i, url in enumerate(urls, 1):
        console.print(f"[{i}/{len(urls)}] Processing: {url[:60]}...", style="dim")
        
        try:
            result = manager.add_player_by_url(url, backfill_history=backfill)
            if result:
                hist_msg = f" (+{result.get('history_count', 0)} history)" if backfill else ""
                console.print(f"  ✓ Added {result['name']}{hist_msg}", style="green")
                added += 1
            else:
                console.print(f"  ✗ Failed to add", style="red")
                failed += 1
        except Exception as e:
            console.print(f"  ✗ Error: {e}", style="red")
            failed += 1
        
        # Rate limiting
        if i < len(urls):
            time.sleep(delay)
    
    console.print(f"\n✓ Import complete: {added} added, {failed} failed", style="green bold")


@player.command('import-starters')
@click.pass_context
def player_import_starters(ctx):
    """Import a starter set of high-value players."""
    from src.player_manager import get_manager, STARTER_PLAYERS
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    console.print(f"Importing {len(STARTER_PLAYERS)} starter players...", style="yellow")
    
    with console.status("Importing players (this may take a minute)..."):
        result = manager.import_players_bulk(STARTER_PLAYERS, fetch_prices=False)
    
    console.print(f"✓ Imported {result['added']} players ({result['failed']} failed)", style="green")


# ========== Price Commands ==========

@cli.group()
def price():
    """Price tracking commands."""
    pass


@price.command('history')
@click.argument('player_id', type=str)
@click.option('--days', '-d', default=7, help='Number of days of history to show')
@click.option('--limit', '-l', default=50, help='Maximum number of records to show')
@click.pass_context  
def price_history(ctx, player_id, days, limit):
    """Show price history for a player."""
    from src.database import get_db
    
    db = get_db()
    
    # Get player info
    player = db.get_player(player_id=player_id)
    if not player:
        console.print(f"Player {player_id} not found", style="red")
        return
    
    history = db.get_price_history(player_id=player_id, platform=ctx.obj['platform'], days=days, limit=limit)
    
    if not history:
        console.print(f"No price history for {player['name']}", style="yellow")
        return
    
    # Calculate stats
    prices = [h['price'] for h in history]
    min_price = min(prices)
    max_price = max(prices)
    avg_price = sum(prices) // len(prices)
    
    console.print(f"\n[bold]{player['name']}[/bold] - Price History ({len(history)} records)")
    console.print(f"Range: {min_price:,} - {max_price:,} | Avg: {avg_price:,}")
    
    table = Table(show_header=True, box=box.SIMPLE)
    table.add_column("Date/Time")
    table.add_column("Price", justify="right", style="cyan")
    table.add_column("vs Avg", justify="right")
    
    for h in history[:limit]:
        diff = h['price'] - avg_price
        diff_pct = (diff / avg_price) * 100
        
        if diff > 0:
            diff_str = f"+{diff:,} (+{diff_pct:.1f}%)"
            diff_style = "green"
        elif diff < 0:
            diff_str = f"{diff:,} ({diff_pct:.1f}%)"
            diff_style = "red"
        else:
            diff_str = "="
            diff_style = "dim"
        
        table.add_row(
            h['recorded_at'].strftime("%Y-%m-%d %H:%M"),
            f"{h['price']:,}",
            f"[{diff_style}]{diff_str}[/{diff_style}]"
        )
    
    console.print(table)


@price.command('fetch')
@click.option('--player-id', '-p', type=int, default=None, help='Fetch for specific player')
@click.pass_context
def price_fetch(ctx, player_id):
    """Fetch current prices from Futbin."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    if player_id:
        with console.status(f"Fetching price for player {player_id}..."):
            price = manager.fetch_price(player_id)
        
        if price:
            console.print(f"✓ Current price: [bold cyan]{price:,}[/bold cyan] coins", style="green")
        else:
            console.print("✗ Could not fetch price", style="red")
    else:
        with console.status("Fetching prices for all active players..."):
            result = manager.fetch_all_prices()
        
        console.print(f"✓ Fetched {result['success']} prices ({result['failed']} failed)", style="green")


# ========== Analysis Commands ==========

@cli.group()
def analyze():
    """Investment analysis commands."""
    pass


@analyze.command('market')
def analyze_market():
    """Show comprehensive FUT market status."""
    from src.fut_calendar import get_calendar
    from datetime import datetime
    
    cal = get_calendar()
    now = datetime.now()
    
    # Header
    console.print(f"\n[bold cyan]{'═' * 60}[/bold cyan]")
    console.print(f"[bold]   📊 FUT MARKET STATUS - {now.strftime('%A, %B %d, %Y %I:%M %p')}[/bold]")
    console.print(f"[bold cyan]{'═' * 60}[/bold cyan]\n")
    
    # === ANNUAL CYCLE ===
    phase = cal.get_current_phase()
    console.print(f"[bold]SEASON PHASE:[/bold] {phase['icon']} {phase['name']}")
    console.print(f"  [dim]{phase['description']}[/dim]")
    console.print(f"  [yellow]Strategy: {phase['strategy']}[/yellow]\n")
    
    # === UPCOMING EVENTS ===
    active = cal.get_active_promo()
    next_promo = cal.get_next_promo()
    next_crash = cal.get_next_crash()
    
    console.print("[bold]EVENTS:[/bold]")
    if active:
        console.print(f"  🔴 [bold red]ACTIVE:[/bold red] {active.name} (ends {active.end_date.strftime('%b %d')})")
        console.print(f"     [dim]{active.trading_notes}[/dim]")
    
    if next_promo and next_promo != active:
        days = cal.days_until_event(next_promo)
        console.print(f"  📅 Next Promo: {next_promo.name} in {days} days ({next_promo.start_date.strftime('%b %d')})")
    
    if next_crash:
        days = cal.days_until_event(next_crash)
        severity_icon = "💥" if next_crash.crash_severity == "extreme" else "⚠️"
        console.print(f"  {severity_icon} [bold]Next Crash:[/bold] {next_crash.name} in {days} days")
        if days <= 14:
            console.print(f"     [red bold]⚠️ LIQUIDATE HIGH-VALUE CARDS SOON[/red bold]")
    
    console.print()
    
    # === WEEKLY CYCLE ===
    weekly = cal.get_weekly_phase()
    console.print("[bold]WEEKLY CYCLE:[/bold]")
    
    # Visual week bar
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    colors = ['green', 'green', 'green', 'yellow', 'red', 'dim', 'dim']
    current = now.weekday()
    
    week_row = "  "
    for i, (d, c) in enumerate(zip(days, colors)):
        if i == current:
            week_row += f"[bold white on blue] {d} [/bold white on blue] "
        else:
            week_row += f"[{c}] {d} [/{c}] "
    console.print(week_row)
    
    console.print(f"\n  [bold]{weekly['action']} {weekly['day'].upper()}[/bold] - {weekly['phase'].replace('_', ' ').title()}")
    console.print(f"  [dim]{weekly['description']}[/dim]")
    console.print(f"  [cyan]→ {weekly['strategy']}[/cyan]")
    
    if 'substrategy' in weekly:
        console.print(f"  [yellow]{weekly['substrategy']}[/yellow]")
    
    console.print()
    
    # === DAILY WINDOW ===
    daily = cal.get_daily_windows()
    console.print(f"[bold]TIME OF DAY:[/bold] {daily['window']}")
    console.print(f"  {daily['action']} - {daily['description']}")
    console.print(f"  [dim]Liquidity: {daily['liquidity']}[/dim]")
    
    if cal.is_content_drop_window():
        console.print(f"\n  [bold yellow]⚡ CONTENT DROP WINDOW - 6PM UK[/bold yellow]")
        console.print(f"  [dim]New SBCs/promos may drop. Watch for price swings.[/dim]")
    
    console.print()
    
    # === QUICK ACTIONS ===
    console.print("[bold]TODAY'S ACTIONS:[/bold]")
    
    if weekly['day'] == 'Thursday':
        console.print("  🟢 Buy meta players this morning (post-rewards flood)")
        console.print("  🟢 Stock up on fodder (cheapest day)")
        console.print("  ⏰ Sell by Friday evening")
    elif weekly['day'] == 'Friday':
        console.print("  🔴 Sell meta cards before Weekend League")
        console.print("  ⏰ Watch 6PM UK for new content")
        console.print("  📋 Don't buy - prices are peaked")
    elif weekly['day'] in ['Monday', 'Tuesday']:
        console.print("  🟢 Buy meta players (post-WL dip)")
        console.print("  🟢 Snipe panic sellers")
        console.print("  ⏰ Hold until Thursday/Friday")
    elif weekly['day'] == 'Wednesday':
        console.print("  🟢 Last buy window before Thursday")
        console.print("  📋 Make your buy list for tomorrow's rewards")
        console.print("  ⏰ Prices will rise Thursday evening")
    else:
        console.print("  ⚪ Weekend League active - minimal trading")
        console.print("  📋 Prepare buy lists for Monday")
    
    console.print(f"\n[bold cyan]{'═' * 60}[/bold cyan]\n")


@analyze.command('calendar')
def analyze_calendar():
    """Show FC 26 promo calendar and crash dates."""
    from src.fut_calendar import get_calendar
    from datetime import datetime
    
    cal = get_calendar()
    now = datetime.now()
    
    console.print("\n[bold]📅 FC 26 PROMO CALENDAR[/bold]\n")
    
    table = Table(box=box.ROUNDED)
    table.add_column("Event", style="bold")
    table.add_column("Dates")
    table.add_column("Crash", justify="center")
    table.add_column("Status")
    table.add_column("Trading Notes", style="dim", max_width=40)
    
    for event in cal.events:
        # Determine status
        if now > event.end_date:
            status = "[dim]Passed[/dim]"
        elif event.start_date <= now <= event.end_date:
            status = "[bold red]ACTIVE[/bold red]"
        else:
            days = (event.start_date - now).days
            status = f"[cyan]In {days} days[/cyan]"
        
        # Crash severity
        crash_icons = {
            'minor': '🟡',
            'moderate': '🟠',
            'major': '🔴',
            'extreme': '💥'
        }
        crash = crash_icons.get(event.crash_severity, '⚪')
        
        table.add_row(
            event.name,
            f"{event.start_date.strftime('%b %d')} - {event.end_date.strftime('%b %d')}",
            crash,
            status,
            event.trading_notes[:40]
        )
    
    console.print(table)
    console.print("\n[dim]Crash: 🟡 Minor | 🟠 Moderate | 🔴 Major | 💥 Extreme[/dim]\n")


@analyze.command('run')
@click.option('--save', '-s', is_flag=True, help='Save signals as alerts')
@click.pass_context
def analyze_run(ctx, save):
    """Run full investment analysis."""
    from src.analyzer import get_analyzer
    
    analyzer = get_analyzer(platform=ctx.obj['platform'])
    
    with console.status("Running analysis..."):
        signals = analyzer.run_full_analysis()
    
    if not signals:
        console.print("No investment signals found", style="yellow")
        return
    
    # Group by severity
    high = [s for s in signals if s.severity == 'high']
    medium = [s for s in signals if s.severity == 'medium']
    low = [s for s in signals if s.severity == 'low']
    
    if high:
        console.print("\n[bold red]🔴 HIGH PRIORITY SIGNALS[/bold red]")
        for s in high:
            console.print(f"  [{s.signal_type.value}] [bold]{s.player_name}[/bold]: {s.message}")
    
    if medium:
        console.print("\n[bold yellow]🟡 MEDIUM PRIORITY SIGNALS[/bold yellow]")
        for s in medium:
            console.print(f"  [{s.signal_type.value}] [bold]{s.player_name}[/bold]: {s.message}")
    
    if low:
        console.print("\n[bold blue]🔵 LOW PRIORITY SIGNALS[/bold blue]")
        for s in low:
            console.print(f"  [{s.signal_type.value}] [bold]{s.player_name}[/bold]: {s.message}")
    
    console.print(f"\n[dim]Total: {len(signals)} signals ({len(high)} high, {len(medium)} medium, {len(low)} low)[/dim]")
    
    if save:
        saved = analyzer.save_signals_as_alerts(signals)
        console.print(f"✓ Saved {saved} alerts to database", style="green")


@analyze.command('player')
@click.argument('player_id', type=int)
@click.pass_context
def analyze_player(ctx, player_id):
    """Analyze a specific player."""
    from src.analyzer import get_analyzer
    
    analyzer = get_analyzer(platform=ctx.obj['platform'])
    analysis = analyzer.get_player_analysis(player_id)
    
    if not analysis or 'message' in analysis:
        console.print(analysis.get('message', 'Player not found'), style="yellow")
        return
    
    player = analysis['player']
    
    console.print(Panel(
        f"[bold]{player['name']}[/bold]\n"
        f"Rating: {player.get('rating', 'N/A')} | Position: {player.get('position', 'N/A')}",
        title="Player Analysis"
    ))
    
    if analysis.get('current_price'):
        console.print(f"Current Price: [bold cyan]{analysis['current_price']:,}[/bold cyan]")
    
    if analysis.get('price_range'):
        pr = analysis['price_range']
        console.print(f"Price Range (30d): {pr['min']:,} - {pr['max']:,} (avg: {pr['avg']:,.0f})")
    
    if analysis.get('change_24h'):
        change = analysis['change_24h']
        color = "green" if change['percent'] > 0 else "red" if change['percent'] < 0 else "white"
        console.print(f"24h Change: [{color}]{change['absolute']:+,} ({change['percent']:+.1f}%)[/{color}]")
    
    if analysis.get('volatility'):
        vol = analysis['volatility']
        console.print(f"Volatility: {vol['coefficient']:.1f}%")


# ========== Alerts Commands ==========

@cli.group()
def alerts():
    """Alert management commands."""
    pass


@alerts.command('list')
@click.option('--all', '-a', 'show_all', is_flag=True, help='Show all alerts (including read)')
def alerts_list(show_all):
    """List recent alerts."""
    from src.database import get_db
    
    db = get_db()
    
    if show_all:
        # Would need to add a method for this
        console.print("Showing all alerts not yet implemented - use unread only", style="yellow")
    
    alerts = db.get_unread_alerts(limit=20)
    
    if not alerts:
        console.print("No unread alerts", style="green")
        return
    
    table = Table(title="Unread Alerts", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Player", style="bold")
    table.add_column("Type")
    table.add_column("Message")
    table.add_column("Price", justify="right", style="cyan")
    table.add_column("Time", style="dim")
    
    for alert in alerts:
        table.add_row(
            str(alert['id']),
            alert['name'],
            alert['alert_type'],
            alert['message'][:50] + "..." if len(alert['message']) > 50 else alert['message'],
            f"{alert['price_at_alert']:,}" if alert['price_at_alert'] else "-",
            alert['created_at'].strftime('%m/%d %H:%M')
        )
    
    console.print(table)


@alerts.command('clear')
@click.option('--alert-id', '-i', type=int, default=None, help='Clear specific alert')
def alerts_clear(alert_id):
    """Mark alerts as read."""
    from src.database import get_db
    
    db = get_db()
    
    if alert_id:
        count = db.mark_alerts_read([alert_id])
    else:
        count = db.mark_alerts_read()
    
    console.print(f"✓ Marked {count} alerts as read", style="green")


# ========== Watchlist Commands ==========

@cli.group()
def watchlist():
    """Watchlist management commands."""
    pass


@watchlist.command('add')
@click.argument('player_id', type=int)
@click.option('--buy', '-b', type=int, default=None, help='Target buy price')
@click.option('--sell', '-s', type=int, default=None, help='Target sell price')
@click.option('--notes', '-n', default=None, help='Notes')
@click.pass_context
def watchlist_add(ctx, player_id, buy, sell, notes):
    """Add a player to watchlist."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    if manager.add_to_watchlist(player_id, target_buy_price=buy, target_sell_price=sell, notes=notes):
        console.print(f"✓ Added player {player_id} to watchlist", style="green")
        if buy:
            console.print(f"  Target buy: {buy:,}")
        if sell:
            console.print(f"  Target sell: {sell:,}")
    else:
        console.print("✗ Failed to add to watchlist", style="red")


@watchlist.command('list')
@click.pass_context
def watchlist_list(ctx):
    """Show your watchlist."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    items = manager.get_watchlist()
    
    if not items:
        console.print("Watchlist is empty", style="yellow")
        return
    
    table = Table(title="Watchlist", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Player", style="bold")
    table.add_column("Current", justify="right", style="cyan")
    table.add_column("Buy Target", justify="right", style="green")
    table.add_column("Sell Target", justify="right", style="red")
    table.add_column("Notes")
    
    for item in items:
        current = f"{item['current_price']:,}" if item.get('current_price') else "-"
        buy = f"{item['target_buy_price']:,}" if item.get('target_buy_price') else "-"
        sell = f"{item['target_sell_price']:,}" if item.get('target_sell_price') else "-"
        notes = (item.get('notes') or "")[:30]
        
        table.add_row(
            str(item['player_id']),
            item['name'],
            current,
            buy,
            sell,
            notes
        )
    
    console.print(table)


@watchlist.command('remove')
@click.argument('player_id', type=int)
@click.pass_context
def watchlist_remove(ctx, player_id):
    """Remove a player from watchlist."""
    from src.player_manager import get_manager
    
    manager = get_manager(platform=ctx.obj['platform'])
    
    if manager.remove_from_watchlist(player_id):
        console.print(f"✓ Removed player {player_id} from watchlist", style="green")
    else:
        console.print("✗ Failed to remove from watchlist", style="red")


# ========== Scheduler Commands ==========

@cli.command('schedule')
@click.pass_context
def schedule(ctx):
    """Start the automated scheduler."""
    from src.scheduler import HazardPayScheduler
    
    print_banner()
    console.print("Starting scheduler... (Ctrl+C to stop)\n", style="yellow")
    
    scheduler = HazardPayScheduler(platform=ctx.obj['platform'], blocking=True)
    
    # Show scheduled jobs
    jobs = scheduler.list_jobs()
    table = Table(title="Scheduled Jobs", box=box.ROUNDED)
    table.add_column("Job")
    table.add_column("Next Run")
    table.add_column("Schedule")
    
    for job in jobs:
        table.add_row(job['name'], str(job['next_run']), job['trigger'])
    
    console.print(table)
    console.print("")
    
    scheduler.start()


@cli.command('run-now')
@click.option('--job', '-j', type=click.Choice(['prices', 'analysis', 'all']), default='all')
@click.pass_context
def run_now(ctx, job):
    """Run scrape/analysis immediately."""
    from src.scheduler import HazardPayScheduler
    
    scheduler = HazardPayScheduler(platform=ctx.obj['platform'], blocking=False)
    
    console.print(f"Running {job} job(s)...", style="yellow")
    scheduler.run_now(job)
    console.print("✓ Complete!", style="green")


# ========== Utility Commands ==========

@cli.command('scrape-test')
@click.argument('futbin_id', type=int)
@click.argument('slug')
@click.option('--debug', '-d', is_flag=True, help='Show raw HTML for debugging')
@click.pass_context
def scrape_test(ctx, futbin_id, slug, debug):
    """Test scraping a player (doesn't save to DB)."""
    from src.scraper import FutbinScraper
    import requests
    from bs4 import BeautifulSoup
    
    scraper = FutbinScraper(platform=ctx.obj['platform'])
    url = scraper.get_player_url(futbin_id, slug)
    
    console.print(f"Scraping {slug} (ID: {futbin_id})...", style="yellow")
    console.print(f"URL: {url}", style="dim")
    
    if debug:
        # Raw debug mode - show what we're getting
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        console.print(f"Status: {response.status_code}", style="dim")
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Check various price selectors
        console.print("\n[bold]Checking selectors:[/bold]")
        
        selectors = [
            'div.price.inline-with-icon.lowest-price-1',
            'div.lowest-price-1',
            '[data-recent-prices]',
            '.player-price',
            '.price-box',
            '.pcdisplay-rat',
        ]
        
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                console.print(f"  ✓ {sel}: {el.text[:50] if el.text else el.attrs}", style="green")
            else:
                console.print(f"  ✗ {sel}: not found", style="red")
        return
    
    result = scraper.get_player_prices(futbin_id, slug)
    
    if result:
        price_str = f"{result.current_price:,}" if result.current_price else "Not found"
        min_str = f"{result.price_min:,}" if result.price_min else "N/A"
        max_str = f"{result.price_max:,}" if result.price_max else "N/A"
        recent_str = ', '.join(str(p) for p in result.recent_prices[:5]) if result.recent_prices else "None"
        
        console.print(Panel(
            f"[bold]Player:[/bold] {result.name}\n"
            f"[bold]Current Price:[/bold] {price_str} coins\n"
            f"[bold]Price Range:[/bold] {min_str} - {max_str}\n"
            f"[bold]Recent Prices:[/bold] {recent_str}\n"
            f"[bold]Platform:[/bold] {result.platform}\n"
            f"[bold]Rating:[/bold] {result.rating or 'N/A'}\n"
            f"[bold]Position:[/bold] {result.position or 'N/A'}",
            title="Scrape Result"
        ))
        
        if not result.current_price:
            console.print("\n[yellow]⚠ Price not found. Run with --debug to check selectors.[/yellow]")
    else:
        console.print("✗ Failed to scrape player", style="red")


@cli.command()
def version():
    """Show version information."""
    from src import __version__
    console.print(f"HazardPay v{__version__}")


@cli.command('market')
@click.option('--refresh', '-r', is_flag=True, help='Force refresh cached data from Futbin')
@click.pass_context
def market_pulse_cmd(ctx, refresh):
    """
    Analyze market health based on your tracked players.
    
    This gives you a real-time view of market conditions by analyzing
    all your tracked players - detecting crashes, recoveries, and inflation.
    
    Data is cached for 6 hours. Use --refresh to force fresh data.
    """
    from src.market_pulse import get_pulse_analyzer
    
    platform = ctx.obj['platform']
    console.print(f"\n[bold]📊 Market Pulse Analysis[/bold] ({platform.upper()})\n", style="cyan")
    
    if refresh:
        # Clear the cache
        from src.database import get_db
        db = get_db()
        db.db.longterm_cache.delete_many({})
        console.print("[dim]Cleared cache, fetching fresh data...[/dim]\n")
    
    analyzer = get_pulse_analyzer(platform=platform)
    
    console.print("Analyzing tracked players...", style="dim")
    pulse = analyzer.get_pulse()
    
    if not pulse:
        console.print("✗ Could not analyze market - need more tracked players", style="red")
        console.print("  Add at least 3 players with 'player add <futbin_url>'", style="dim")
        return
    
    # Status color
    status_colors = {
        "CRASHED": "bold green",
        "CRASHING": "yellow",
        "STABLE": "white",
        "RECOVERING": "cyan",
        "INFLATED": "bold red"
    }
    
    sentiment_colors = {
        "GREAT": "bold green",
        "GOOD": "green",
        "NEUTRAL": "white", 
        "RISKY": "yellow",
        "AVOID": "bold red"
    }
    
    # Main status panel
    status_color = status_colors.get(pulse.status, "white")
    console.print(Panel(
        pulse.summary,
        title=f"Market Status: {pulse.status}",
        style=status_color
    ))
    
    # Detailed metrics table
    table = Table(title="Market Metrics", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    table.add_column("Meaning", style="dim")
    
    table.add_row(
        "Players Analyzed",
        str(pulse.players_analyzed),
        "Sample size"
    )
    table.add_row(
        "Avg Position",
        f"{pulse.avg_position_in_range:.0f}%",
        "0% = all-time lows, 100% = all-time highs"
    )
    table.add_row(
        "At Lows (<25%)",
        f"{pulse.pct_at_lows:.0f}%",
        "% of players near all-time lows"
    )
    table.add_row(
        "At Highs (>75%)",
        f"{pulse.pct_at_highs:.0f}%",
        "% of players near all-time highs"
    )
    table.add_row(
        "Trending Down",
        f"{pulse.pct_trending_down:.0f}%",
        "% dropping in last 24h"
    )
    table.add_row(
        "Trending Up",
        f"{pulse.pct_trending_up:.0f}%",
        "% rising in last 24h"
    )
    table.add_row(
        "Fodder Status",
        pulse.fodder_status,
        f"Position: {pulse.fodder_avg_position:.0f}%"
    )
    
    console.print(table)
    
    # Category Breakdown Table
    if pulse.categories:
        cat_table = Table(title="Category Breakdown", box=box.ROUNDED)
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Count", justify="center")
        cat_table.add_column("Position", justify="center")
        cat_table.add_column("At Lows", justify="center")
        cat_table.add_column("At Highs", justify="center")
        cat_table.add_column("Status", justify="center")
        
        # Sort categories: Premium first, then fodder by tier
        category_order = ['Icons', 'Heroes', 'TOTY', 'TOTW', '89+ Fodder', '87-88 Fodder', '86 Fodder', '85 Fodder']
        sorted_cats = sorted(
            pulse.categories.items(),
            key=lambda x: category_order.index(x[0]) if x[0] in category_order else 99
        )
        
        for cat_name, cat_pulse in sorted_cats:
            if cat_pulse.count == 0:
                continue
            
            # Status with color
            status_style = {
                'CRASHED': 'bold green',
                'LOW': 'green',
                'NORMAL': 'white',
                'HIGH': 'yellow',
                'INFLATED': 'bold red'
            }.get(cat_pulse.status, 'white')
            
            cat_table.add_row(
                cat_name,
                str(cat_pulse.count),
                f"{cat_pulse.avg_position:.0f}%",
                f"{cat_pulse.pct_at_lows:.0f}%",
                f"{cat_pulse.pct_at_highs:.0f}%",
                f"[{status_style}]{cat_pulse.status_emoji} {cat_pulse.status}[/{status_style}]"
            )
        
        console.print(cat_table)
    
    # Sentiment
    console.print(f"\n[bold]Trading Sentiment:[/bold]")
    buy_color = sentiment_colors.get(pulse.buy_sentiment, "white")
    sell_color = sentiment_colors.get(pulse.sell_sentiment, "white")
    
    console.print(f"  Buy:  [{buy_color}]{pulse.buy_sentiment}[/{buy_color}]")
    console.print(f"  Sell: [{sell_color}]{pulse.sell_sentiment}[/{sell_color}]")
    
    # Interpretation
    console.print(f"\n[dim]Based on {pulse.players_analyzed} tracked players • {pulse.timestamp.strftime('%Y-%m-%d %H:%M')}[/dim]")


@cli.command()
@click.argument('futbin_id', type=int)
@click.argument('slug', type=str)
@click.option('--limit', '-l', default=20, help='Number of price points to show')
@click.pass_context
def history_test(ctx, futbin_id, slug, limit):
    """Test historical price scraping from Futbin sales page."""
    from src.scraper import FutbinScraper
    
    scraper = FutbinScraper(platform=ctx.obj['platform'])
    
    console.print(f"Fetching historical prices for {slug}...", style="yellow")
    
    prices = scraper.get_historical_prices(futbin_id, slug)
    
    if prices:
        console.print(f"\n✓ Found [bold]{len(prices)}[/bold] historical price points!", style="green")
        
        # Show price range
        price_values = [p.price for p in prices]
        console.print(f"  Range: {min(price_values):,} - {max(price_values):,} coins")
        console.print(f"  Period: {prices[-1].timestamp.date()} to {prices[0].timestamp.date()}")
        
        # Show recent prices
        console.print(f"\n[bold]Most Recent {min(limit, len(prices))} Prices:[/bold]")
        table = Table(show_header=True)
        table.add_column("Date/Time")
        table.add_column("Price", justify="right")
        
        for hp in prices[:limit]:
            table.add_row(
                hp.timestamp.strftime("%Y-%m-%d %H:%M"),
                f"{hp.price:,}"
            )
        console.print(table)
    else:
        console.print("✗ No historical prices found", style="red")


# ========== Portfolio Commands ==========

@cli.group()
def portfolio():
    """Portfolio & position management."""
    pass


@portfolio.command('buy')
@click.argument('player_name', type=str)
@click.argument('price', type=int)
@click.option('--qty', '-q', default=1, help='Quantity bought')
@click.option('--target', '-t', type=int, default=None, help='Target sell price')
@click.option('--type', '-T', 'pos_type', default='meta', type=click.Choice(['fodder', 'meta']), help='Investment type')
@click.option('--notes', '-n', default='', help='Trade notes')
@click.pass_context
def portfolio_buy(ctx, player_name, price, qty, target, pos_type, notes):
    """Record a buy position."""
    from src.portfolio import get_portfolio
    from src.database import get_db
    
    db = get_db()
    
    # Find player by name (case-insensitive partial match)
    player = db.db.players.find_one({
        'name': {'$regex': player_name, '$options': 'i'}
    })
    
    if not player:
        console.print(f"Player '{player_name}' not found", style="red")
        return
    
    pf = get_portfolio(platform=ctx.obj['platform'])
    
    position_id = pf.add_position(
        player_id=str(player['_id']),
        buy_price=price,
        quantity=qty,
        position_type=pos_type,
        target_sell_price=target,
        notes=notes
    )
    
    if position_id:
        total = price * qty
        console.print(f"✓ Position recorded: {qty}x @ {price:,} = {total:,} coins", style="green")
        if target:
            profit = (target * 0.95 - price) * qty
            console.print(f"  Target: {target:,} (potential profit: {profit:,.0f} after tax)")
    else:
        console.print("✗ Failed to record position", style="red")


@portfolio.command('sell')
@click.argument('position_id', type=str)
@click.argument('price', type=int)
def portfolio_sell(position_id, price):
    """Close a position (record sale)."""
    from src.portfolio import get_portfolio
    
    pf = get_portfolio()
    
    if pf.close_position(position_id, price):
        console.print(f"✓ Position closed at {price:,}", style="green")
    else:
        console.print("✗ Failed to close position", style="red")


@portfolio.command('list')
@click.option('--closed', '-c', is_flag=True, help='Show closed positions instead')
@click.pass_context
def portfolio_list(ctx, closed):
    """Show open positions with P&L."""
    from src.portfolio import get_portfolio
    
    pf = get_portfolio(platform=ctx.obj['platform'])
    
    if closed:
        positions = pf.get_closed_positions(days=30)
        title = "Closed Positions (Last 30 Days)"
    else:
        positions = pf.get_open_positions()
        title = "Open Positions"
    
    if not positions:
        console.print(f"No {title.lower()} found", style="yellow")
        return
    
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Player", style="bold")
    table.add_column("Type")
    table.add_column("Qty", justify="center")
    table.add_column("Buy", justify="right")
    table.add_column("Current" if not closed else "Sold", justify="right", style="cyan")
    table.add_column("P&L", justify="right")
    table.add_column("P&L %", justify="right")
    
    total_pl = 0
    
    for pos in positions:
        if closed:
            current = pos.get('sell_price', 0)
            pl = pos.get('profit_after_tax', 0)
            pl_pct = pos.get('profit_pct', 0)
        else:
            current = pos.get('current_price', 0)
            pl = pos.get('profit_after_tax', 0)
            pl_pct = pos.get('profit_pct_after_tax', 0)
        
        total_pl += pl or 0
        
        # Color P&L
        if pl and pl > 0:
            pl_str = f"[green]+{pl:,}[/green]"
            pct_str = f"[green]+{pl_pct:.1f}%[/green]"
        elif pl and pl < 0:
            pl_str = f"[red]{pl:,}[/red]"
            pct_str = f"[red]{pl_pct:.1f}%[/red]"
        else:
            pl_str = "-"
            pct_str = "-"
        
        table.add_row(
            str(pos['id'])[:8],
            pos['player_name'],
            pos.get('position_type', 'meta'),
            str(pos.get('quantity', 1)),
            f"{pos['buy_price']:,}",
            f"{current:,}" if current else "-",
            pl_str,
            pct_str
        )
    
    console.print(table)
    
    # Summary
    if total_pl > 0:
        console.print(f"\n[bold green]Total P&L: +{total_pl:,} coins[/bold green]")
    elif total_pl < 0:
        console.print(f"\n[bold red]Total P&L: {total_pl:,} coins[/bold red]")


@portfolio.command('summary')
@click.pass_context
def portfolio_summary(ctx):
    """Show portfolio summary stats."""
    from src.portfolio import get_portfolio
    
    pf = get_portfolio(platform=ctx.obj['platform'])
    stats = pf.get_portfolio_summary()
    
    console.print("\n[bold]📊 PORTFOLIO SUMMARY[/bold]\n")
    
    console.print("[bold]Open Positions:[/bold]")
    console.print(f"  Positions: {stats['open_positions']}")
    console.print(f"  Invested: {stats['total_invested']:,} coins")
    console.print(f"  Current Value: {stats['current_value']:,} coins")
    
    if stats['unrealized_pl'] >= 0:
        console.print(f"  Unrealized P&L: [green]+{stats['unrealized_pl']:,}[/green] ({stats['unrealized_pct']:.1f}%)")
    else:
        console.print(f"  Unrealized P&L: [red]{stats['unrealized_pl']:,}[/red] ({stats['unrealized_pct']:.1f}%)")
    
    console.print(f"\n[bold]Last 30 Days:[/bold]")
    console.print(f"  Closed Trades: {stats['closed_30d']}")
    
    if stats['realized_pl_30d'] >= 0:
        console.print(f"  Realized P&L: [green]+{stats['realized_pl_30d']:,}[/green]")
    else:
        console.print(f"  Realized P&L: [red]{stats['realized_pl_30d']:,}[/red]")
    
    console.print(f"  Win Rate: {stats['win_rate']:.0f}% ({stats['wins']}W / {stats['losses']}L)")


@portfolio.command('signals')
@click.pass_context
def portfolio_signals(ctx):
    """Check buy/sell signals for your positions."""
    from src.portfolio import get_portfolio
    from src.smart_signals import get_smart_signals
    
    pf = get_portfolio(platform=ctx.obj['platform'])
    signals = get_smart_signals(platform=ctx.obj['platform'])
    
    positions = pf.get_open_positions()
    
    if not positions:
        console.print("No open positions", style="yellow")
        return
    
    console.print("\n[bold]📡 POSITION SIGNALS[/bold]\n")
    
    for pos in positions:
        signal = signals.get_sell_score(pos['player_id'], pos['buy_price'])
        
        if not signal:
            continue
        
        # Header
        if signal.score >= 65:
            style = "green"
        elif signal.score >= 50:
            style = "yellow"
        else:
            style = "dim"
        
        console.print(f"[bold]{pos['player_name']}[/bold] - [{style}]{signal.signal_type} ({signal.score}/100)[/{style}]")
        console.print(f"  Bought: {pos['buy_price']:,} | Current: {signal.current_price:,}")
        
        pl = pos.get('profit_after_tax', 0)
        if pl and pl > 0:
            console.print(f"  P&L: [green]+{pl:,}[/green] (after tax)")
        elif pl:
            console.print(f"  P&L: [red]{pl:,}[/red] (after tax)")
        
        for reason in signal.reasons:
            console.print(f"    {reason}", style="green")
        for warning in signal.warnings:
            console.print(f"    {warning}", style="yellow")
        
        console.print(f"  → {signal.recommendation}\n")


# ========== Smart Scan Commands ==========

@cli.command()
@click.option('--min-score', '-m', default=60, help='Minimum score to show')
@click.pass_context
def scan_buys(ctx, min_score):
    """Scan all players for buy opportunities."""
    from src.smart_signals import get_smart_signals
    
    signals = get_smart_signals(platform=ctx.obj['platform'])
    
    console.print("[bold]🔍 Scanning for buy opportunities...[/bold]\n")
    
    opportunities = signals.scan_buy_opportunities(min_score=min_score)
    
    if not opportunities:
        console.print(f"No players with buy score >= {min_score}", style="yellow")
        console.print("[dim]Try lowering --min-score or wait for better market conditions[/dim]")
        return
    
    for signal in opportunities:
        if signal.score >= 80:
            style = "bold green"
            icon = "🟢"
        elif signal.score >= 65:
            style = "green"
            icon = "🟡"
        else:
            style = "yellow"
            icon = "⚪"
        
        console.print(f"{icon} [{style}]{signal.signal_type}[/{style}] [bold]{signal.player_name}[/bold] (Score: {signal.score}/100)")
        console.print(f"   Price: {signal.current_price:,} coins")
        
        for reason in signal.reasons:
            console.print(f"   {reason}", style="green")
        for warning in signal.warnings:
            console.print(f"   {warning}", style="yellow")
        
        console.print(f"   → {signal.recommendation}\n")


@cli.command()
@click.option('--sort', '-s', type=click.Choice(['score', 'name', 'price']), default='score', help='Sort by')
@click.pass_context
def scores(ctx, sort):
    """Show all players with their buy scores in a table."""
    from src.smart_signals import get_smart_signals
    from src.database import get_db
    from rich.table import Table
    
    db = get_db()
    signals = get_smart_signals(platform=ctx.obj['platform'])
    
    console.print("[bold]📊 Calculating buy scores for all players...[/bold]\n")

    players = db.get_all_players()

    # Pre-warm longterm cache before scoring loop
    signals.refresh_longterm_cache(players)

    results = []

    for p in players:
        signal = signals.get_buy_score(p['id'])
        if signal:
            results.append({
                'name': signal.player_name,
                'score': signal.score,
                'type': signal.signal_type,
                'price': signal.current_price,
                'velocity': signal.velocity.state if signal.velocity else 'N/A',
                'buy_ready': signal.velocity.buy_readiness if signal.velocity else 'N/A',
                'confidence': signal.confidence,
                'reasons': signal.reasons[:1] if signal.reasons else [],
            })
    
    # Sort results
    if sort == 'score':
        results.sort(key=lambda x: x['score'], reverse=True)
    elif sort == 'name':
        results.sort(key=lambda x: x['name'])
    elif sort == 'price':
        results.sort(key=lambda x: x['price'], reverse=True)
    
    # Build table
    table = Table(title="Buy Scores (V3)", show_lines=False)
    table.add_column("Player", style="cyan", no_wrap=True)
    table.add_column("Score", justify="center")
    table.add_column("Signal", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("State", justify="center")
    table.add_column("Ready?", justify="center")
    table.add_column("Conf", justify="center")
    
    for r in results:
        # Color code score
        if r['score'] >= 80:
            score_str = f"[bold green]{r['score']}[/bold green]"
        elif r['score'] >= 60:
            score_str = f"[green]{r['score']}[/green]"
        elif r['score'] >= 40:
            score_str = f"[yellow]{r['score']}[/yellow]"
        else:
            score_str = f"[red]{r['score']}[/red]"
        
        # Signal type color
        if r['type'] in ['STRONG_BUY', 'STRONG BUY']:
            type_str = f"[bold green]{r['type']}[/bold green]"
        elif r['type'] == 'BUY':
            type_str = f"[green]{r['type']}[/green]"
        elif r['type'] == 'HOLD':
            type_str = f"[yellow]{r['type']}[/yellow]"
        else:
            type_str = f"[red]{r['type']}[/red]"
        
        # Momentum color
        vel = r['velocity']
        if vel in ['STABLE', 'BOTTOMING']:
            vel_str = f"[green]{vel}[/green]"
        elif vel in ['RISING', 'DECELERATING']:
            vel_str = f"[cyan]{vel}[/cyan]"
        elif vel == 'SURGING':
            vel_str = f"[bold green]{vel}[/bold green]"
        elif vel == 'FALLING':
            vel_str = f"[yellow]{vel}[/yellow]"
        elif vel == 'FREEFALL':
            vel_str = f"[red]{vel}[/red]"
        else:
            vel_str = vel
        
        # Buy readiness color
        ready = r['buy_ready']
        if ready == 'READY':
            ready_str = f"[bold green]✓ READY[/bold green]"
        elif ready == 'ALMOST':
            ready_str = f"[cyan]⏳ ALMOST[/cyan]"
        elif ready == 'WAIT':
            ready_str = f"[yellow]⏸ WAIT[/yellow]"
        else:
            ready_str = f"[red]✗ AVOID[/red]"
        
        # Confidence color
        conf = r['confidence']
        if conf == 'HIGH':
            conf_str = f"[green]{conf}[/green]"
        elif conf == 'MEDIUM':
            conf_str = f"[yellow]{conf}[/yellow]"
        else:
            conf_str = f"[red]{conf}[/red]"
        
        table.add_row(
            r['name'][:25],
            score_str,
            type_str,
            f"{r['price']:,}",
            vel_str,
            ready_str,
            conf_str
        )
    
    console.print(table)
    
    # Summary
    strong_buys = len([r for r in results if r['score'] >= 80])
    buys = len([r for r in results if 60 <= r['score'] < 80])
    holds = len([r for r in results if 40 <= r['score'] < 60])
    avoids = len([r for r in results if r['score'] < 40])
    
    console.print(f"\n[green]STRONG BUY: {strong_buys}[/green] | [green]BUY: {buys}[/green] | [yellow]HOLD: {holds}[/yellow] | [red]AVOID: {avoids}[/red]")


@cli.command()
@click.argument('player_name', type=str)
@click.pass_context
def check_buy(ctx, player_name):
    """Check if now is a good time to buy a specific player."""
    from src.smart_signals import get_smart_signals
    from src.database import get_db
    
    db = get_db()
    
    # Find player by name (case-insensitive partial match)
    player = db.db.players.find_one({
        'name': {'$regex': player_name, '$options': 'i'}
    })
    
    if not player:
        console.print(f"Player '{player_name}' not found", style="red")
        return
    
    signals = get_smart_signals(platform=ctx.obj['platform'])

    # Pre-warm longterm cache for this player
    signals.refresh_longterm_cache([player])

    signal = signals.get_buy_score(str(player['_id']))
    
    if not signal:
        console.print("Player not found or no data", style="red")
        return
    
    # Score bar
    score = signal.score
    bar_filled = int(score / 5)
    bar_empty = 20 - bar_filled
    
    if score >= 80:
        bar_color = "green"
    elif score >= 65:
        bar_color = "yellow"
    elif score >= 50:
        bar_color = "yellow"
    else:
        bar_color = "red"
    
    console.print(f"\n[bold]BUY ANALYSIS: {signal.player_name}[/bold]")
    console.print(f"Current Price: [cyan]{signal.current_price:,}[/cyan] coins\n")
    
    bar = f"[{bar_color}]{'█' * bar_filled}[/{bar_color}][dim]{'░' * bar_empty}[/dim]"
    console.print(f"Score: {bar} {score}/100")
    console.print(f"Signal: [bold]{signal.signal_type}[/bold]\n")
    
    if signal.reasons:
        console.print("[bold green]✓ Positive Factors:[/bold green]")
        for r in signal.reasons:
            console.print(f"  {r}")
    
    if signal.warnings:
        console.print("\n[bold yellow]⚠ Concerns:[/bold yellow]")
        for w in signal.warnings:
            console.print(f"  {w}")
    
    console.print(f"\n[bold]Recommendation:[/bold] {signal.recommendation}")


# ========== Continuous Monitor Command ==========

@cli.command()
@click.option('--interval', '-i', default=10, help='Scrape interval in minutes')
@click.option('--buy-threshold', '-b', default=75, help='Alert when buy score >= this')
@click.option('--sell-threshold', '-s', default=70, help='Alert when sell score >= this')
@click.option('--sound', is_flag=True, help='Play sound on alerts (macOS)')
@click.pass_context
def monitor(ctx, interval, buy_threshold, sell_threshold, sound):
    """
    🔴 LIVE MONITOR - Continuously scrape and alert on signals.
    
    This runs in the foreground, scraping prices every X minutes
    and alerting you when:
    
    \b
    • A player hits your BUY threshold (default: 75+)
    • An open position hits your SELL threshold (default: 70+)
    
    Press Ctrl+C to stop.
    """
    import time
    from datetime import datetime
    from src.player_manager import PlayerManager
    from src.smart_signals import get_smart_signals
    from src.portfolio import get_portfolio
    
    platform = ctx.obj['platform']
    pm = PlayerManager(platform=platform)
    signals = get_smart_signals(platform=platform)
    portfolio = get_portfolio()
    
    # Track alerted players to avoid spam
    alerted_buys = set()
    alerted_sells = set()
    
    def play_alert_sound():
        """Play alert sound on macOS."""
        if sound:
            try:
                import subprocess
                subprocess.run(['afplay', '/System/Library/Sounds/Glass.aiff'], capture_output=True)
            except:
                pass
    
    def display_alert(alert_type, signal):
        """Display a prominent alert."""
        play_alert_sound()
        
        if alert_type == "BUY":
            color = "green"
            emoji = "🟢"
            border_style = "bold green"
        else:
            color = "cyan"
            emoji = "💰"
            border_style = "bold cyan"
        
        alert_text = Text()
        alert_text.append(f"\n{emoji} ", style="bold")
        alert_text.append(f"{alert_type} SIGNAL: ", style=f"bold {color}")
        alert_text.append(f"{signal.player_name}\n", style="bold white")
        alert_text.append(f"Score: {signal.score}/100 | ", style=color)
        alert_text.append(f"Price: {signal.current_price:,}\n", style="white")
        
        for reason in signal.reasons[:3]:
            alert_text.append(f"  ✓ {reason}\n", style="green")
        
        alert_text.append(f"\n→ {signal.recommendation}", style="bold")
        
        panel = Panel(
            alert_text,
            title=f"⚡ {alert_type} ALERT",
            border_style=border_style,
            expand=False
        )
        console.print(panel)
    
    def run_scan():
        """Run a single scan cycle."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Get all tracked players
        players = pm.get_all_players()
        if not players:
            return
        
        console.print(f"\n[dim]── Scan at {timestamp} ──[/dim]")
        
        # Update prices
        updated = 0
        for p in players:
            try:
                # Use 'id' which is the string player_id returned by get_all_players
                player_id = p.get('id')
                if player_id:
                    pm.fetch_price(player_id)
                    updated += 1
            except Exception as e:
                logger.warning(f"Failed to update {p['name']}: {e}")
        
        console.print(f"[dim]Updated {updated}/{len(players)} players[/dim]")
        
        # Check buy signals for watchlist
        buy_opportunities = signals.scan_buy_opportunities(min_score=buy_threshold)
        for signal in buy_opportunities:
            player_id = str(signal.player_id)
            if player_id not in alerted_buys:
                display_alert("BUY", signal)
                alerted_buys.add(player_id)
        
        # Clear alerts if score dropped below threshold
        current_buy_ids = {str(s.player_id) for s in buy_opportunities}
        alerted_buys.intersection_update(current_buy_ids)
        
        # Check sell signals for open positions
        open_positions = portfolio.get_open_positions()
        for pos in open_positions:
            sell_signal = signals.get_sell_score(
                str(pos['player_id']),
                pos['buy_price']
            )
            if sell_signal and sell_signal.score >= sell_threshold:
                pos_key = str(pos['_id'])
                if pos_key not in alerted_sells:
                    display_alert("SELL", sell_signal)
                    alerted_sells.add(pos_key)
        
        # Show quick summary
        if not buy_opportunities and not open_positions:
            console.print("[dim]No signals above threshold[/dim]")
        elif buy_opportunities and not any(str(s.player_id) in alerted_buys for s in buy_opportunities):
            console.print(f"[dim]Watching {len(buy_opportunities)} opportunities below alert level[/dim]")
    
    # Initial display
    console.print("\n[bold red]🔴 LIVE MONITOR ACTIVE[/bold red]")
    console.print(f"[dim]Platform: {platform.upper()} | Interval: {interval}m | Buy ≥{buy_threshold} | Sell ≥{sell_threshold}[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")
    
    # Show current state
    players = pm.get_all_players()
    positions = portfolio.get_open_positions()
    console.print(f"📊 Tracking [cyan]{len(players)}[/cyan] players")
    console.print(f"💼 [cyan]{len(positions)}[/cyan] open positions")
    
    # Run initial scan
    run_scan()
    
    # Main loop
    try:
        while True:
            time.sleep(interval * 60)
            run_scan()
    except KeyboardInterrupt:
        console.print("\n\n[bold yellow]Monitor stopped.[/bold yellow]")


# ========== Quick Status Command ==========

@cli.command()
@click.pass_context
def status(ctx):
    """Quick status overview - positions, signals, and market."""
    from src.player_manager import PlayerManager
    from src.smart_signals import get_smart_signals
    from src.portfolio import get_portfolio
    from src.market_pulse import get_pulse_analyzer
    from datetime import datetime
    
    platform = ctx.obj['platform']
    pm = PlayerManager(platform=platform)
    signals = get_smart_signals(platform=platform)
    portfolio = get_portfolio()
    pulse_analyzer = get_pulse_analyzer(platform=platform)
    
    console.print("\n[bold]📊 HAZARDPAY STATUS[/bold]\n")
    
    # Market Pulse - Real conditions based on tracked players
    pulse = pulse_analyzer.get_pulse()
    if pulse:
        status_colors = {
            "CRASHED": "bold green",
            "CRASHING": "yellow", 
            "STABLE": "white",
            "RECOVERING": "cyan",
            "INFLATED": "bold red"
        }
        status_color = status_colors.get(pulse.status, "white")
        console.print(f"🌡️  [{status_color}]{pulse.summary}[/{status_color}]")
        console.print(f"   [dim]Avg position: {pulse.avg_position_in_range:.0f}% | {pulse.pct_at_lows:.0f}% at lows | {pulse.pct_trending_down:.0f}% dropping[/dim]")
    else:
        console.print("[dim]🌡️  Need more tracked players for market pulse[/dim]")
    
    # Top buy opportunities
    buy_opps = signals.scan_buy_opportunities(min_score=60)[:3]
    if buy_opps:
        console.print(f"\n[bold green]🟢 Top Buy Opportunities:[/bold green]")
        for sig in buy_opps:
            score_str = f"[bold]{sig.score}[/bold]" if sig.score >= 75 else str(sig.score)
            console.print(f"   {sig.player_name}: {score_str}/100 @ {sig.current_price:,}")
    
    # Open positions
    positions = portfolio.get_open_positions()
    if positions:
        console.print(f"\n[bold cyan]💼 Open Positions:[/bold cyan]")
        total_pnl = 0
        for pos in positions:
            current = pos.get('current_price', pos['buy_price'])
            sell_after_tax = int(current * 0.95)
            pnl = (sell_after_tax - pos['buy_price']) * pos['quantity']
            total_pnl += pnl
            
            pnl_color = "green" if pnl > 0 else "red"
            console.print(f"   {pos['player_name']}: [{pnl_color}]{pnl:+,}[/{pnl_color}] ({current:,} now)")
        
        console.print(f"   [bold]Total: [{pnl_color}]{total_pnl:+,}[/{pnl_color}] coins[/bold]")
    else:
        console.print(f"\n[dim]💼 No open positions[/dim]")
    
    # Tracking count
    players = pm.get_all_players()
    console.print(f"\n[dim]Tracking {len(players)} players[/dim]")


# ========== Scheduler Command ==========

@cli.command('scheduler')
@click.option('--interval', '-i', default=15, help='Update interval in minutes')
@click.pass_context
def scheduler_cmd(ctx, interval):
    """Run price updates on a schedule (every 15 min by default)."""
    import time
    from datetime import datetime
    
    platform = ctx.obj['platform']
    
    console.print(Panel.fit(
        f"[bold cyan]HAZARDPAY SCHEDULER[/bold cyan]\n"
        f"Updates every {interval} minutes\n"
        f"Platform: {platform}\n"
        f"Press Ctrl+C to stop",
        border_style="cyan"
    ))
    
    from src.player_manager import get_manager
    manager = get_manager(platform=platform)
    
    def run_update():
        timestamp = datetime.now().strftime("%H:%M:%S")
        players = manager.get_all_players()
        
        if not players:
            console.print(f"[{timestamp}] No players to update", style="yellow")
            return
        
        console.print(f"\n[{timestamp}] [bold]Updating {len(players)} players...[/bold]")
        
        success = 0
        for p in players:
            try:
                price = manager.fetch_price(p['id'])
                if price:
                    console.print(f"  ✓ {p['name']}: {price:,}", style="dim green")
                    success += 1
                else:
                    console.print(f"  ✗ {p['name']}: failed", style="dim red")
            except Exception as e:
                console.print(f"  ✗ {p['name']}: {e}", style="dim red")
        
        console.print(f"[{timestamp}] ✓ Updated {success}/{len(players)} players", style="bold green")
        
        next_time = datetime.now().timestamp() + (interval * 60)
        next_str = datetime.fromtimestamp(next_time).strftime("%H:%M:%S")
        console.print(f"[dim]Next update at {next_str}[/dim]\n")
    
    # Run immediately
    run_update()
    
    try:
        while True:
            time.sleep(interval * 60)
            run_update()
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped[/yellow]")


# ========== ML Pipeline Commands ==========

@cli.command('enrich-cards')
@click.option('--force', '-f', is_flag=True, help='Re-enrich even if card_type already set')
@click.option('--player', '-p', type=str, default=None, help='Enrich a specific player by name')
@click.pass_context
def enrich_cards(ctx, force, player):
    """Step 1: Enrich player cards with card_type and first_seen_at."""
    from src.ml_pipeline import MLPipeline

    pipeline = MLPipeline(platform=ctx.obj['platform'])

    if player:
        from src.database import get_db
        db = get_db()
        p = db.db.players.find_one({'name': {'$regex': player, '$options': 'i'}})
        if not p:
            console.print(f"Player '{player}' not found", style="red")
            return
        slug = p.get('slug') or p.get('name', '').lower().replace(' ', '-')
        result = pipeline.enrich_player(p['futbin_id'], slug, force=force)
        console.print(f"Enriched {p['name']}: card_type={result.get('card_type')}, "
                      f"first_seen={result.get('first_seen_at')}, source={result.get('source')}")
        return

    console.print("[bold]Enriching all players with card_type and first_seen_at...[/bold]\n")
    results = pipeline.enrich_all_players(force=force)

    table = Table(title="Card Metadata Enrichment", box=box.SIMPLE)
    table.add_column("Player", style="cyan")
    table.add_column("Card Type", style="bold")
    table.add_column("First Seen")
    table.add_column("Source", style="dim")

    enriched = 0
    skipped = 0
    for r in results:
        if r.get('skipped'):
            skipped += 1
        else:
            enriched += 1

        first_seen_str = r['first_seen_at'].strftime('%Y-%m-%d') if r.get('first_seen_at') else '-'
        source_str = r.get('source', '-')
        table.add_row(r['name'], r.get('card_type', '?'), first_seen_str, source_str)

    console.print(table)
    console.print(f"\n[bold green]Enriched: {enriched}[/bold green]  [dim]Skipped (existing): {skipped}[/dim]")


@cli.command('label-signals')
@click.option('--min-age', '-a', default=7, type=int, help='Minimum age in days before labeling')
@click.option('--stats', '-s', is_flag=True, help='Show labeled data statistics')
@click.pass_context
def label_signals_cmd(ctx, min_age, stats):
    """Step 2: Label signals with actual price outcomes (what happened after each signal)."""
    from src.ml_pipeline import MLPipeline

    pipeline = MLPipeline(platform=ctx.obj['platform'])

    if stats:
        label_stats = pipeline.get_label_stats()
        if label_stats['total'] == 0:
            console.print("No labeled signals yet. Run [bold]label-signals[/bold] first.", style="yellow")
            return

        console.print(f"[bold]Labeled Signals: {label_stats['total']}[/bold]\n")

        if label_stats.get('by_direction'):
            console.print("[bold]By Direction:[/bold]")
            for direction, count in label_stats['by_direction'].items():
                console.print(f"  {direction}: {count}")

        if label_stats.get('by_card_type'):
            console.print("\n[bold]By Card Type:[/bold]")
            table = Table(box=box.SIMPLE)
            table.add_column("Card Type")
            table.add_column("Count", justify="right")
            table.add_column("Avg 7D Return", justify="right")
            for ct, data in sorted(label_stats['by_card_type'].items()):
                avg_ret = f"{data['avg_return_7d']:+.1f}%" if data.get('avg_return_7d') is not None else '-'
                table.add_row(ct, str(data['count']), avg_ret)
            console.print(table)
        return

    console.print("[bold]Labeling signals with actual outcomes...[/bold]\n")
    result = pipeline.label_signals(min_age_days=min_age)

    console.print(f"  Labeled:          [green]{result['labeled']}[/green]")
    console.print(f"  Already labeled:  [dim]{result['already_labeled']}[/dim]")
    console.print(f"  No price data:    [red]{result['skipped_no_price']}[/red]")

    from src.database import get_db
    total = get_db().db.labeled_signals.count_documents({})
    console.print(f"\n[bold]Total labeled signals: {total}[/bold]")


@cli.command('baselines')
@click.option('--card-type', '-t', default=None, help='Filter by card type')
@click.option('--new-cards', '-n', is_flag=True, help='Show time-to-bottom patterns for new cards')
@click.pass_context
def baselines_cmd(ctx, card_type, new_cards):
    """Step 3: Show statistical baselines for signal accuracy by card type."""
    from src.ml_pipeline import MLPipeline

    pipeline = MLPipeline(platform=ctx.obj['platform'])

    if new_cards:
        patterns = pipeline.compute_new_card_patterns()
        if not patterns:
            console.print("No cards with first_seen_at data. Run [bold]enrich-cards[/bold] first.", style="yellow")
            return

        table = Table(title="Time-to-Bottom by Card Type", box=box.ROUNDED)
        table.add_column("Card Type", style="bold")
        table.add_column("Samples", justify="right")
        table.add_column("Avg Days", justify="right")
        table.add_column("Median Days", justify="right")
        table.add_column("Avg Drop %", justify="right")

        for p in patterns:
            table.add_row(
                p['card_type'],
                str(p['sample_size']),
                str(p['avg_days_to_bottom']),
                str(p['median_days_to_bottom']),
                f"{p['avg_drop_pct']:.1f}%",
            )

        console.print(table)

        # Show individual entries per type
        for p in patterns:
            console.print(f"\n[bold]{p['card_type']}[/bold] details:")
            detail_table = Table(box=box.SIMPLE)
            detail_table.add_column("Player")
            detail_table.add_column("Days to Bottom", justify="right")
            detail_table.add_column("Drop %", justify="right")
            detail_table.add_column("First Price", justify="right")
            detail_table.add_column("Bottom Price", justify="right")
            for e in p['entries']:
                detail_table.add_row(
                    e['player'],
                    str(e['days_to_bottom']),
                    f"{e['drop_pct']:.1f}%",
                    f"{e['first_price']:,}",
                    f"{e['bottom_price']:,}",
                )
            console.print(detail_table)
        return

    baselines = pipeline.compute_baselines()
    if not baselines:
        console.print("No labeled data. Run [bold]label-signals[/bold] first.", style="yellow")
        return

    for ct, data in baselines.items():
        if card_type and ct != card_type:
            continue

        console.print(f"\n[bold]{ct}[/bold] ({data['total_signals']} signals)")

        table = Table(box=box.SIMPLE)
        table.add_column("Score Range")
        table.add_column("N", justify="right")
        table.add_column("Avg 2D", justify="right")
        table.add_column("Avg 7D", justify="right")
        table.add_column("Hit 2D", justify="right")
        table.add_column("Hit 7D", justify="right")
        table.add_column("Win 7D", justify="right")

        for row in data['by_score_range']:
            if row['n'] == 0:
                table.add_row(row['range'], '0', '-', '-', '-', '-', '-')
                continue

            ret_2d = row.get('avg_return_2d')
            ret_7d = row.get('avg_return_7d')
            table.add_row(
                row['range'],
                str(row['n']),
                f"{ret_2d:+.1f}%" if ret_2d is not None else '-',
                f"{ret_7d:+.1f}%" if ret_7d is not None else '-',
                f"{row.get('hit_rate_2d', 0):.0f}%" if row.get('hit_rate_2d') is not None else '-',
                f"{row.get('hit_rate_7d', 0):.0f}%" if row.get('hit_rate_7d') is not None else '-',
                f"{row.get('win_rate_7d', 0):.0f}%" if row.get('win_rate_7d') is not None else '-',
            )

        console.print(table)


@cli.command('eval-ml')
@click.option('--min-samples', '-n', default=100, type=int, help='Minimum labeled samples required')
@click.pass_context
def eval_ml_cmd(ctx, min_samples):
    """Step 4: Evaluate if ML improves over statistical baselines."""
    from src.ml_pipeline import MLPipeline

    pipeline = MLPipeline(platform=ctx.obj['platform'])

    total = pipeline.db.db.labeled_signals.count_documents({
        'direction': 'BUY', 'return_7d_pct': {'$ne': None}
    })

    if total < min_samples:
        console.print(f"Need {min_samples} labeled BUY signals, have {total}.", style="yellow")
        console.print("Run [bold]label-signals[/bold] periodically to build up data.", style="dim")
        return

    try:
        from sklearn.ensemble import GradientBoostingRegressor
    except ImportError:
        console.print("scikit-learn required. Install with: [bold]pip install scikit-learn[/bold]", style="red")
        return

    console.print(f"[bold]Evaluating ML on {total} labeled signals...[/bold]\n")

    try:
        result = pipeline.evaluate_ml()
    except ValueError as e:
        console.print(f"Error: {e}", style="red")
        return

    table = Table(title="Baseline vs ML", box=box.ROUNDED)
    table.add_column("Metric")
    table.add_column("Baseline", justify="right")
    table.add_column("ML (GBT)", justify="right")
    table.add_column("Delta", justify="right")

    table.add_row(
        "MAE (lower=better)",
        f"{result['baseline_mae']:.2f}%",
        f"{result['ml_mae']:.2f}%",
        f"{result['improvement_pct']:+.1f}%",
    )
    table.add_row(
        "Direction Accuracy",
        f"{result['baseline_hit_rate']:.0f}%",
        f"{result['ml_hit_rate']:.0f}%",
        f"{result['ml_hit_rate'] - result['baseline_hit_rate']:+.1f}%",
    )

    console.print(table)
    console.print(f"\nTrain: {result['train_size']} | Test: {result['test_size']}")

    console.print("\n[bold]Top 10 Features:[/bold]")
    for feat, importance in result['top_features']:
        bar_len = int(importance * 100)
        console.print(f"  {feat:35s} {importance:.4f} {'█' * bar_len}")

    if result['recommendation'] == 'ADOPT_ML':
        console.print(
            "\n[bold green]Recommendation: ML improves over baselines by >15%. Worth adopting.[/bold green]"
        )
    else:
        console.print(
            "\n[bold yellow]Recommendation: ML does not meaningfully improve. Keep statistical baselines.[/bold yellow]"
        )


def main():
    """Main entry point."""
    print_banner()
    cli(obj={})


if __name__ == '__main__':
    main()
