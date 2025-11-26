#!/usr/bin/env python3
"""
Reddit Smart Pain Listener (RSS-based) - Main Entry Point
==========================================================

A context-aware Reddit listener that uses sentiment analysis
to find GENUINE pain points (negative sentiment only).

Features:
- HTML cleaning from Reddit RSS feeds
- VADER sentiment analysis (tuned for social media)
- Context window extraction (sentence + before/after)
- CSV logging of high-quality pain points
- Rich console alerts (color-coded by severity)

Usage:
    python main.py              # Start the smart listener
    python main.py --stats      # Show pain point statistics
    python main.py --csv        # View recent CSV entries
    python main.py --reset      # Clear seen posts (fresh start)

No Reddit API credentials required - uses public RSS feeds.

Author: Smart Pain Listener
License: MIT
"""

import os
import sys
import signal
import logging
import argparse
from pathlib import Path
from datetime import datetime
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
from rich.logging import RichHandler

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    NICHES,
    validate_config,
    LOG_LEVEL,
    LOG_FILE,
    POLL_INTERVAL_MIN,
    POLL_INTERVAL_MAX,
    extract_keywords_from_query,
)
from src.rss_listener import RSSListener, RSSPost
from src.pain_logger import PainLogger, print_session_summary
from src.pain_analyzer import PainPoint
from src.web.app import run_server_background, broadcast_pain_point

# Initialize Rich console
console = Console()


# ============================================================================
# NICHE STYLING
# ============================================================================

NICHE_COLORS = {
    "Sweaty_Startup": "bright_yellow",
    "Agency_Owners": "bright_cyan",
    "Ecommerce_Ops": "bright_magenta",
    "Content_Creators": "bright_green",
    "Recruiters": "bright_blue",
}

NICHE_EMOJIS = {
    "Sweaty_Startup": "🔧",
    "Agency_Owners": "📊",
    "Ecommerce_Ops": "🛒",
    "Content_Creators": "🎬",
    "Recruiters": "👔",
}


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging(quiet: bool = False) -> None:
    """Configure logging with Rich handler."""
    log_dir = Path(LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]

    if not quiet:
        handlers.insert(0, RichHandler(
            console=console,
            rich_tracebacks=True,
            show_time=True,
            show_path=False,
        ))

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )

    # Reduce noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("nltk").setLevel(logging.WARNING)


# ============================================================================
# STARTUP DISPLAY
# ============================================================================

def print_startup_banner() -> None:
    """Display startup banner."""
    banner_text = Text()
    banner_text.append("🎯 ", style="bold")
    banner_text.append("Smart Pain Point Listener", style="bold red")
    banner_text.append(" (Sentiment-Aware)", style="bold yellow")
    banner_text.append("\n\n", style="")
    banner_text.append("Only logs NEGATIVE sentiment matches.\n", style="italic dim")
    banner_text.append("Filters out positive/neutral noise automatically.", style="italic dim")

    console.print(Panel(
        banner_text,
        box=box.DOUBLE,
        border_style="red",
        padding=(1, 4),
    ))
    console.print()


def print_niche_summary() -> None:
    """Display niche configuration."""
    table = Table(
        title="📊 Monitored Niches",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Niche", style="bold")
    table.add_column("Subreddits", style="blue")
    table.add_column("Pain Keywords", style="red", max_width=40)

    for niche_name, niche_data in NICHES.items():
        color = NICHE_COLORS.get(niche_name, "white")
        emoji = NICHE_EMOJIS.get(niche_name, "🔔")
        subs = ", ".join(niche_data["subreddits"])

        # Extract keywords for display
        keywords = extract_keywords_from_query(niche_data["search_query"])
        keywords_str = ", ".join(keywords[:4])
        if len(keywords) > 4:
            keywords_str += f" (+{len(keywords)-4})"

        table.add_row(
            Text(f"{emoji} {niche_name.replace('_', ' ')}", style=color),
            subs,
            keywords_str,
        )

    console.print(table)
    console.print()

    # Print polling info
    console.print(f"[dim]Poll interval: [bold]{POLL_INTERVAL_MIN//60}-{POLL_INTERVAL_MAX//60} minutes[/bold][/dim]")
    console.print(f"[dim]Sentiment threshold: [bold]< -0.05[/bold] (negative only)[/dim]")
    console.print()


def print_status_config(port: int = 8080) -> None:
    """Display current status configuration."""
    status_table = Table(show_header=False, box=box.SIMPLE)
    status_table.add_column("Item", style="bold")
    status_table.add_column("Status")

    status_table.add_row("Mode", "[red]🎯 SNIPER MODE[/red] (negative sentiment only)")
    status_table.add_row("Analysis", "[green]✓ VADER Sentiment[/green] + Context Windows")
    status_table.add_row("Output", "[green]✓ CSV[/green] (data/pain_points.csv)")
    status_table.add_row("Console", "[green]✓ Rich Alerts[/green] (color-coded)")
    status_table.add_row("Dashboard", f"[green]✓ http://localhost:{port}[/green]")

    console.print(Panel(
        status_table,
        title="🔧 Configuration",
        border_style="green",
        box=box.ROUNDED,
    ))
    console.print()


def validate_and_warn() -> bool:
    """Validate configuration."""
    issues = validate_config()

    if not issues:
        console.print("[green]✓ Configuration validated[/green]")
        console.print()
        return True

    console.print(Panel(
        "\n".join(f"[yellow]![/yellow] {issue}" for issue in issues),
        title="⚠️ Warnings",
        border_style="yellow",
        box=box.ROUNDED,
    ))
    console.print()
    return True


# ============================================================================
# MAIN LISTENER
# ============================================================================

def run_listener(port: int = 8080) -> None:
    """Run the main smart pain listener with web dashboard."""
    logger = logging.getLogger(__name__)

    # Display startup info
    print_startup_banner()
    print_niche_summary()
    print_status_config(port=port)
    validate_and_warn()

    # Start web dashboard FIRST for Railway healthcheck
    console.print(f"[bold green]🌐 Starting web dashboard at http://0.0.0.0:{port}[/bold green]")
    run_server_background(port=port)

    # Open browser only if running locally (not on Railway)
    import os
    if not os.getenv('RAILWAY_ENVIRONMENT'):
        import webbrowser
        from threading import Thread
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(f'http://localhost:{port}')
        Thread(target=open_browser, daemon=True).start()

    # Initialize pain logger
    pain_logger = PainLogger()

    # Stats counters
    stats = {
        "pain_posts": 0,
        "filtered": 0,
    }

    def on_pain_point(post: RSSPost) -> None:
        """Handle posts with pain points (negative sentiment)."""
        stats["pain_posts"] += 1

        # Log each pain point to CSV and broadcast to web
        for pain_point in post.pain_points:
            entry = pain_logger.log_pain_point(
                pain_point=pain_point,
                niche=post.niche,
                subreddit=post.subreddit,
                reddit_url=post.full_url,
                post_title=post.title,
                author=post.author
            )

            # Broadcast to web clients
            try:
                broadcast_pain_point({
                    'timestamp': entry.timestamp.isoformat(),
                    'niche': entry.niche,
                    'subreddit': entry.subreddit,
                    'keyword': entry.keyword,
                    'pain_score': f"{entry.pain_score:.3f}",
                    'severity': entry.severity,
                    'context_snippet': entry.context_snippet,
                    'reddit_url': entry.reddit_url,
                    'post_title': entry.post_title,
                    'author': entry.author,
                })
            except Exception as e:
                logger.debug(f"Failed to broadcast: {e}")

    def on_neutral_match(post: RSSPost) -> None:
        """Track filtered neutral/positive posts."""
        stats["filtered"] += 1

    # Initialize RSS listener
    listener = RSSListener(
        on_pain_point=on_pain_point,
        on_neutral_match=on_neutral_match
    )

    # Graceful shutdown
    def signal_handler(signum, frame):
        console.print("\n[yellow]Shutdown signal received...[/yellow]")
        listener.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start
    console.print("[bold red]🎯 Starting Smart Pain Listener...[/bold red]")
    console.print("[dim]Only NEGATIVE sentiment matches will be logged.[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    try:
        listener.start(POLL_INTERVAL_MIN, POLL_INTERVAL_MAX)
    except KeyboardInterrupt:
        pass
    finally:
        console.print()
        console.print(Panel(
            Text("📊 Session Summary", style="bold cyan"),
            box=box.DOUBLE,
            border_style="cyan"
        ))

        # Print session stats
        summary_table = Table(show_header=False, box=box.ROUNDED)
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Value", justify="right")

        summary_table.add_row("Poll cycles", str(listener.poll_count))
        summary_table.add_row("🔴 Pain posts found", f"[red]{stats['pain_posts']}[/red]")
        summary_table.add_row("⚪ Filtered (neutral/positive)", f"[dim]{listener.neutral_filtered}[/dim]")
        summary_table.add_row("Total posts scanned", str(listener.total_posts_seen))
        summary_table.add_row("Pain points logged", f"[bold red]{pain_logger.log_count}[/bold red]")

        console.print(summary_table)
        console.print()

        # Show CSV stats
        csv_stats = pain_logger.get_csv_stats()
        if csv_stats["total_entries"] > 0:
            console.print(f"[dim]📁 Total in CSV: {csv_stats['total_entries']} pain points[/dim]")
            console.print(f"[dim]📁 File: data/pain_points.csv[/dim]")

        console.print()
        console.print("[green]✓ Listener stopped. Goodbye![/green]")


# ============================================================================
# STATS COMMAND
# ============================================================================

def show_stats() -> None:
    """Show pain point statistics from CSV."""
    pain_logger = PainLogger()
    stats = pain_logger.get_csv_stats()

    console.print()
    console.print(Panel(
        Text("📊 Pain Point Statistics", style="bold cyan"),
        box=box.DOUBLE,
        border_style="cyan"
    ))
    console.print()

    if stats["total_entries"] == 0:
        console.print("[yellow]No pain points logged yet. Run the listener first![/yellow]")
        return

    # Summary table
    summary_table = Table(title="Overall Stats", box=box.ROUNDED)
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value", justify="right")

    summary_table.add_row("Total Pain Points", str(stats["total_entries"]))
    summary_table.add_row("🔴 Severe", f"[red]{stats['by_severity']['SEVERE']}[/red]")
    summary_table.add_row("🟠 Moderate", f"[yellow]{stats['by_severity']['MODERATE']}[/yellow]")
    summary_table.add_row("🟡 Mild", f"[bright_yellow]{stats['by_severity']['MILD']}[/bright_yellow]")

    console.print(summary_table)
    console.print()

    # By niche
    if stats["by_niche"]:
        niche_table = Table(title="By Niche", box=box.ROUNDED)
        niche_table.add_column("Niche", style="bold")
        niche_table.add_column("Count", justify="right")

        sorted_niches = sorted(stats["by_niche"].items(), key=lambda x: x[1], reverse=True)
        for niche, count in sorted_niches:
            emoji = NICHE_EMOJIS.get(niche, "🔔")
            color = NICHE_COLORS.get(niche, "white")
            niche_table.add_row(
                Text(f"{emoji} {niche.replace('_', ' ')}", style=color),
                str(count)
            )

        console.print(niche_table)
        console.print()

    # Top keywords
    if stats["by_keyword"]:
        kw_table = Table(title="Top Pain Keywords", box=box.ROUNDED)
        kw_table.add_column("Keyword", style="bold red")
        kw_table.add_column("Count", justify="right")

        sorted_keywords = sorted(stats["by_keyword"].items(), key=lambda x: x[1], reverse=True)[:10]
        for kw, count in sorted_keywords:
            kw_table.add_row(kw, str(count))

        console.print(kw_table)
        console.print()


# ============================================================================
# VIEW CSV COMMAND
# ============================================================================

def view_csv(limit: int = 10) -> None:
    """View recent CSV entries."""
    import csv

    csv_path = Path("data/pain_points.csv")
    if not csv_path.exists():
        console.print("[yellow]No pain points logged yet.[/yellow]")
        return

    console.print()
    console.print(Panel(
        Text(f"📁 Recent Pain Points (last {limit})", style="bold cyan"),
        box=box.DOUBLE,
        border_style="cyan"
    ))
    console.print()

    # Read CSV
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        console.print("[yellow]CSV is empty.[/yellow]")
        return

    # Show last N entries
    recent = rows[-limit:]

    table = Table(box=box.ROUNDED, show_lines=True)
    table.add_column("Time", style="dim", width=12)
    table.add_column("Niche", width=15)
    table.add_column("Keyword", style="red", width=15)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Context", max_width=50)

    for row in recent:
        # Parse timestamp
        ts = row.get("timestamp", "")[:16].replace("T", " ")

        # Severity color
        severity = row.get("severity", "MILD")
        if severity == "SEVERE":
            score_style = "bold red"
        elif severity == "MODERATE":
            score_style = "yellow"
        else:
            score_style = "dim"

        # Truncate context
        context = row.get("context_snippet", "")[:80]
        if len(row.get("context_snippet", "")) > 80:
            context += "..."

        table.add_row(
            ts,
            row.get("niche", "").replace("_", " "),
            row.get("keyword", ""),
            Text(row.get("pain_score", "0"), style=score_style),
            context
        )

    console.print(table)
    console.print()
    console.print(f"[dim]Total entries: {len(rows)} | File: {csv_path}[/dim]")


# ============================================================================
# RESET COMMAND
# ============================================================================

def reset_seen_posts() -> None:
    """Clear seen posts for a fresh start."""
    seen_file = Path("data/seen_posts.json")

    if seen_file.exists():
        seen_file.unlink()
        console.print("[green]✓ Cleared seen posts. Fresh start![/green]")
    else:
        console.print("[yellow]No seen posts file found.[/yellow]")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Smart Pain Point Listener - Sentiment-Aware Reddit Monitor"
    )
    parser.add_argument("--stats", action="store_true", help="Show pain point statistics")
    parser.add_argument("--csv", action="store_true", help="View recent CSV entries")
    parser.add_argument("--csv-limit", type=int, default=10, help="Number of CSV entries to show")
    parser.add_argument("--reset", action="store_true", help="Clear seen posts (fresh start)")
    parser.add_argument("--quiet", action="store_true", help="Minimal console output")
    parser.add_argument("--port", type=int, default=8080, help="Web dashboard port (default: 8080)")
    args = parser.parse_args()

    setup_logging(quiet=args.quiet)

    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    if args.reset:
        reset_seen_posts()
        return

    if args.stats:
        show_stats()
        return

    if args.csv:
        view_csv(limit=args.csv_limit)
        return

    # Default: run listener with dashboard
    run_listener(port=args.port)


if __name__ == "__main__":
    main()
