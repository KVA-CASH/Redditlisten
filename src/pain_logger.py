"""
Pain Logger Module - Database and Console Output for Pain Points.

Handles:
1. Database logging (PostgreSQL/SQLite)
2. CSV file logging (Legacy/Backup)
3. Rich console alerts with color-coded severity
"""

import csv
import logging
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Any, Dict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .pain_analyzer import PainPoint
from .storage import PostStorage

logger = logging.getLogger(__name__)
console = Console()

# Thread lock for file operations
_file_lock = threading.Lock()


# ============================================================================ 
# CONFIGURATION
# ============================================================================ 

DEFAULT_CSV_PATH = "data/pain_points.csv"

CSV_COLUMNS = [
    "timestamp",
    "niche",
    "subreddit",
    "keyword",
    "pain_score",
    "severity",
    "context_snippet",
    "reddit_url",
    "post_title",
    "author"
]


# ============================================================================ 
# DATA CLASSES
# ============================================================================ 

@dataclass
class PainLogEntry:
    """A complete pain point log entry."""
    timestamp: datetime
    niche: str
    subreddit: str
    keyword: str
    pain_score: float
    severity: str
    context_snippet: str
    reddit_url: str
    post_title: str
    author: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DB storage."""
        return {
            "timestamp": self.timestamp,
            "niche": self.niche,
            "subreddit": self.subreddit,
            "keyword": self.keyword,
            "pain_score": self.pain_score,
            "severity": self.severity,
            "context_snippet": self.context_snippet,
            "reddit_url": self.reddit_url,
            "post_title": self.post_title,
            "author": self.author
        }

    def to_csv_row(self) -> List[str]:
        """Convert to CSV row."""
        return [
            self.timestamp.isoformat(),
            self.niche,
            self.subreddit,
            self.keyword,
            f"{self.pain_score:.3f}",
            self.severity,
            self.context_snippet.replace('\n', ' '),
            self.reddit_url,
            self.post_title[:100],
            self.author
        ]


# ============================================================================ 
# PAIN LOGGER CLASS
# ============================================================================ 

class PainLogger:
    """
    Logs pain points to Database/CSV and displays Rich console alerts.
    """

    def __init__(self, csv_path: str = DEFAULT_CSV_PATH):
        """
        Initialize the logger.

        Args:
            csv_path: Path to the CSV output file
        """
        self.csv_path = Path(csv_path)
        self._ensure_csv_exists()
        self._log_count = 0
        
        # Initialize Storage (DB)
        self.storage = PostStorage()
        
        logger.info(f"PainLogger initialized: {self.csv_path}")

    def _ensure_csv_exists(self) -> None:
        """Create CSV file with headers if it doesn't exist."""
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.csv_path.exists():
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)
            logger.info(f"Created new CSV file: {self.csv_path}")

    def log_pain_point(
        self,
        pain_point: PainPoint,
        niche: str,
        subreddit: str,
        reddit_url: str,
        post_title: str,
        author: str = "unknown"
    ) -> PainLogEntry:
        """
        Log a single pain point to DB, CSV and console.

        Args:
            pain_point: The PainPoint object
            niche: Niche category
            subreddit: Source subreddit
            reddit_url: Link to the Reddit post
            post_title: Title of the post
            author: Post author

        Returns:
            The created PainLogEntry
        """
        entry = PainLogEntry(
            timestamp=datetime.now(),
            niche=niche,
            subreddit=subreddit,
            keyword=pain_point.keyword,
            pain_score=pain_point.pain_score,
            severity=pain_point.severity,
            context_snippet=pain_point.context_snippet,
            reddit_url=reddit_url,
            post_title=post_title,
            author=author
        )

        # 1. Save to Database (Primary Storage)
        self.storage.save_pain_point(entry.to_dict())

        # 2. Write to CSV (Backup/Local)
        self._write_to_csv(entry)

        # 3. Display console alert
        self._display_alert(entry)

        self._log_count += 1
        return entry

    def _write_to_csv(self, entry: PainLogEntry) -> None:
        """Thread-safe CSV write."""
        with _file_lock:
            try:
                with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(entry.to_csv_row())
                logger.debug(f"Logged to CSV: {entry.keyword}")
            except IOError as e:
                logger.error(f"Failed to write to CSV: {e}")

    def _display_alert(self, entry: PainLogEntry) -> None:
        """Display a rich console alert for a pain point."""
        # Color based on severity
        if entry.severity == "SEVERE":
            border_color = "red"
            severity_style = "bold white on red"
            emoji = "🔴"
        elif entry.severity == "MODERATE":
            border_color = "yellow"
            severity_style = "bold black on yellow"
            emoji = "🟠"
        else:
            border_color = "bright_yellow"
            severity_style = "bold black on bright_yellow"
            emoji = "🟡"

        # Build header
        header = Text()
        header.append(f"{emoji} PAIN POINT DETECTED ", style=f"bold {border_color}")
        header.append(f"[{entry.severity}]", style=severity_style)

        # Build content table
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Field", style="dim", width=12)
        table.add_column("Value")

        # Niche & subreddit
        table.add_row("Niche", Text(entry.niche.replace("_", " "), style="bold cyan"))
        table.add_row("Subreddit", Text(f"r/{entry.subreddit}", style="bold blue"))

        # Keyword with highlight
        keyword_text = Text()
        keyword_text.append(f"🎯 {entry.keyword}", style=f"bold {border_color}")
        table.add_row("Keyword", keyword_text)

        # Pain score
        score_style = "red" if entry.pain_score <= -0.5 else "yellow"
        table.add_row("Pain Score", Text(f"{entry.pain_score:.3f}", style=f"bold {score_style}"))

        # Context snippet (truncated for display)
        snippet = entry.context_snippet
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        table.add_row("Context", Text(f'"{snippet}"', style="italic"))

        # Post title
        title_display = entry.post_title[:80] + "..." if len(entry.post_title) > 80 else entry.post_title
        table.add_row("Post", Text(title_display, style="white"))

        # Author
        table.add_row("Author", Text(f"u/{entry.author}", style="dim"))

        # URL
        table.add_row("Link", Text(entry.reddit_url, style="underline blue"))

        # Print panel
        panel = Panel(
            table,
            title=header,
            title_align="left",
            border_style=border_color,
            box=box.DOUBLE,
            padding=(1, 2),
        )

        console.print()
        console.print(panel)
        console.print()

    def log_multiple(
        self,
        pain_points: List[PainPoint],
        niche: str,
        subreddit: str,
        reddit_url: str,
        post_title: str,
        author: str = "unknown"
    ) -> List[PainLogEntry]:
        """
        Log multiple pain points from the same post.

        Args:
            pain_points: List of PainPoint objects
            niche: Niche category
            subreddit: Source subreddit
            reddit_url: Link to the Reddit post
            post_title: Title of the post
            author: Post author

        Returns:
            List of created PainLogEntry objects
        """
        entries = []
        for pp in pain_points:
            entry = self.log_pain_point(
                pain_point=pp,
                niche=niche,
                subreddit=subreddit,
                reddit_url=reddit_url,
                post_title=post_title,
                author=author
            )
            entries.append(entry)
        return entries

    @property
    def log_count(self) -> int:
        """Total number of pain points logged."""
        return self._log_count

    def get_csv_stats(self) -> dict:
        """Get statistics from the CSV file (legacy/local stats)."""
        stats = {
            "total_entries": 0,
            "by_niche": {},
            "by_severity": {"SEVERE": 0, "MODERATE": 0, "MILD": 0},
            "by_keyword": {}
        }

        if not self.csv_path.exists():
            return stats

        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    stats["total_entries"] += 1

                    # By niche
                    niche = row.get("niche", "Unknown")
                    stats["by_niche"][niche] = stats["by_niche"].get(niche, 0) + 1

                    # By severity
                    severity = row.get("severity", "MILD")
                    if severity in stats["by_severity"]:
                        stats["by_severity"][severity] += 1

                    # By keyword
                    keyword = row.get("keyword", "unknown")
                    stats["by_keyword"][keyword] = stats["by_keyword"].get(keyword, 0) + 1

        except Exception as e:
            logger.error(f"Error reading CSV stats: {e}")

        return stats


# ============================================================================ 
# UTILITY FUNCTIONS
# ============================================================================ 

def get_pain_logger(csv_path: str = DEFAULT_CSV_PATH) -> PainLogger:
    """Get a singleton PainLogger instance."""
    if not hasattr(get_pain_logger, '_instance'):
        get_pain_logger._instance = PainLogger(csv_path)
    return get_pain_logger._instance


def print_session_summary(pain_logger: PainLogger) -> None:
    """Print a summary of the current session."""
    stats = pain_logger.get_csv_stats()

    console.print()
    console.print(Panel(
        Text("📊 Pain Point Session Summary", style="bold cyan"),
        box=box.DOUBLE,
        border_style="cyan"
    ))
    console.print()

    summary_table = Table(show_header=False, box=box.ROUNDED)
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value", justify="right")

    summary_table.add_row("Total Pain Points", str(stats["total_entries"]))
    summary_table.add_row("🔴 Severe", str(stats["by_severity"]["SEVERE"]))
    summary_table.add_row("🟠 Moderate", str(stats["by_severity"]["MODERATE"]))
    summary_table.add_row("🟡 Mild", str(stats["by_severity"]["MILD"]))
    summary_table.add_row("Session Logged", str(pain_logger.log_count))

    console.print(summary_table)

    # Top keywords
    if stats["by_keyword"]:
        console.print()
        console.print("[bold]Top Keywords:[/bold]")
        sorted_keywords = sorted(
            stats["by_keyword"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        for kw, count in sorted_keywords:
            console.print(f"  • {kw}: [cyan]{count}[/cyan]")

    console.print()