"""
Notification Module.
Handles console output (Rich) and webhook notifications (Discord/Slack).
"""

import json
import logging
from datetime import datetime
from typing import Optional

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .config import get_notification_config, NotificationConfig
from .listener import MatchedPost
from .storage import PostStorage

logger = logging.getLogger(__name__)

# Rich console for beautiful terminal output
console = Console()


# ============================================================================
# NICHE COLOR MAPPING - For visual distinction in console
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
# CONSOLE NOTIFICATION (Rich)
# ============================================================================

def notify_console(post: MatchedPost) -> None:
    """
    Display a high-visibility notification in the terminal using Rich.
    """
    niche_color = NICHE_COLORS.get(post.niche, "white")
    niche_emoji = NICHE_EMOJIS.get(post.niche, "🔔")

    # Build the header
    header = Text()
    header.append(f"{niche_emoji} ", style="bold")
    header.append(f"[{post.niche}]", style=f"bold {niche_color}")
    header.append(" • ", style="dim")
    header.append(f"r/{post.subreddit}", style="bold blue")

    # Build keyword badges
    keywords_text = Text()
    for i, kw in enumerate(post.matched_keywords):
        if i > 0:
            keywords_text.append(" ")
        keywords_text.append(f"[{kw}]", style=f"bold {niche_color} reverse")

    # Build the content table
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Field", style="dim", width=12)
    table.add_column("Value")

    # Truncate title if too long
    title_display = post.title[:100] + "..." if len(post.title) > 100 else post.title

    table.add_row("Title", Text(title_display, style="bold white"))
    table.add_row("Keywords", keywords_text)
    table.add_row("Author", Text(f"u/{post.author}", style="cyan"))
    table.add_row("Score", Text(f"⬆ {post.score}", style="green" if post.score >= 0 else "red"))
    table.add_row("Comments", Text(f"💬 {post.num_comments}", style="yellow"))
    table.add_row("Posted", Text(post.created_datetime.strftime("%Y-%m-%d %H:%M:%S"), style="dim"))
    table.add_row("Link", Text(post.full_url, style="underline blue"))

    # If there's body text, show a preview
    if post.selftext and post.selftext.strip():
        body_preview = post.selftext[:200].replace("\n", " ")
        if len(post.selftext) > 200:
            body_preview += "..."
        table.add_row("Preview", Text(body_preview, style="dim italic"))

    # Create and print the panel
    panel = Panel(
        table,
        title=header,
        title_align="left",
        border_style=niche_color,
        box=box.DOUBLE,
        padding=(1, 2),
    )

    console.print()
    console.print(panel)
    console.print()


# ============================================================================
# DISCORD WEBHOOK
# ============================================================================

def notify_discord(post: MatchedPost, webhook_url: str) -> bool:
    """
    Send notification to Discord webhook.

    Returns:
        True if successful, False otherwise.
    """
    if not webhook_url:
        logger.warning("Discord webhook URL not configured")
        return False

    niche_emoji = NICHE_EMOJIS.get(post.niche, "🔔")

    # Discord embed colors (decimal)
    embed_colors = {
        "Sweaty_Startup": 16776960,      # Yellow
        "Agency_Owners": 65535,           # Cyan
        "Ecommerce_Ops": 16711935,        # Magenta
        "Content_Creators": 65280,        # Green
        "Recruiters": 255,                # Blue
    }

    embed = {
        "title": f"{niche_emoji} {post.title[:256]}",
        "url": post.full_url,
        "color": embed_colors.get(post.niche, 8421504),  # Default gray
        "fields": [
            {
                "name": "🏷️ Niche",
                "value": post.niche.replace("_", " "),
                "inline": True,
            },
            {
                "name": "📍 Subreddit",
                "value": f"r/{post.subreddit}",
                "inline": True,
            },
            {
                "name": "👤 Author",
                "value": f"u/{post.author}",
                "inline": True,
            },
            {
                "name": "🔑 Keywords Matched",
                "value": ", ".join(post.matched_keywords) or "N/A",
                "inline": False,
            },
        ],
        "footer": {
            "text": f"⬆ {post.score} | 💬 {post.num_comments} | Reddit Listener Bot"
        },
        "timestamp": datetime.utcfromtimestamp(post.created_utc).isoformat(),
    }

    # Add body preview if available
    if post.selftext and post.selftext.strip():
        body_preview = post.selftext[:500]
        if len(post.selftext) > 500:
            body_preview += "..."
        embed["description"] = body_preview

    payload = {
        "embeds": [embed],
    }

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        logger.debug(f"Discord notification sent for post {post.id}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Discord notification: {e}")
        return False


# ============================================================================
# SLACK WEBHOOK (Placeholder)
# ============================================================================

def notify_slack(post: MatchedPost, webhook_url: str) -> bool:
    """
    Send notification to Slack webhook.

    Returns:
        True if successful, False otherwise.
    """
    if not webhook_url:
        logger.warning("Slack webhook URL not configured")
        return False

    niche_emoji = NICHE_EMOJIS.get(post.niche, "🔔")

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{niche_emoji} Pain Point Found!",
                    "emoji": True,
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Niche:*\n{post.niche.replace('_', ' ')}"},
                    {"type": "mrkdwn", "text": f"*Subreddit:*\nr/{post.subreddit}"},
                    {"type": "mrkdwn", "text": f"*Author:*\nu/{post.author}"},
                    {"type": "mrkdwn", "text": f"*Keywords:*\n{', '.join(post.matched_keywords)}"},
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*<{post.full_url}|{post.title[:100]}>*",
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"⬆️ {post.score} | 💬 {post.num_comments}",
                    }
                ]
            },
            {"type": "divider"},
        ]
    }

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        logger.debug(f"Slack notification sent for post {post.id}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


# ============================================================================
# UNIFIED NOTIFICATION DISPATCHER
# ============================================================================

class NotificationDispatcher:
    """
    Central dispatcher for all notification channels.
    Now includes storage for analytics and recommendations.
    """

    def __init__(self, config: Optional[NotificationConfig] = None, storage: Optional[PostStorage] = None):
        self.config = config or get_notification_config()
        self.storage = storage
        self._notification_count = 0

    def send(self, post: MatchedPost) -> None:
        """
        Send notification to all enabled channels and save to storage.
        """
        self._notification_count += 1

        # Save to database for analytics
        if self.storage:
            try:
                self.storage.save_post(post)
            except Exception as e:
                logger.error(f"Failed to save post to storage: {e}")

        # Console notification (primary)
        if self.config.enable_console:
            try:
                notify_console(post)
            except Exception as e:
                logger.error(f"Console notification failed: {e}")

        # Discord notification
        if self.config.enable_discord and self.config.discord_webhook_url:
            try:
                notify_discord(post, self.config.discord_webhook_url)
            except Exception as e:
                logger.error(f"Discord notification failed: {e}")

        # Slack notification
        if self.config.enable_slack and self.config.slack_webhook_url:
            try:
                notify_slack(post, self.config.slack_webhook_url)
            except Exception as e:
                logger.error(f"Slack notification failed: {e}")

    @property
    def notification_count(self) -> int:
        return self._notification_count


# ============================================================================
# PLACEHOLDER FOR CUSTOM NOTIFICATIONS
# ============================================================================

def send_notification(post: MatchedPost) -> None:
    """
    Placeholder function for custom notification implementations.

    This is the hook point for adding your own notification logic.
    Examples:
        - Email notifications
        - Telegram bot
        - SMS via Twilio
        - Database logging
        - Custom API calls

    Args:
        post: The matched Reddit post to notify about.
    """
    # Example: Log to file
    # with open("matches.log", "a") as f:
    #     f.write(f"{post.created_datetime} | {post.niche} | {post.full_url}\n")

    # Example: Telegram (pseudo-code)
    # telegram_bot.send_message(
    #     chat_id=MY_CHAT_ID,
    #     text=f"New pain point in {post.niche}: {post.full_url}"
    # )

    # Example: Database insert (pseudo-code)
    # db.insert("matched_posts", {
    #     "post_id": post.id,
    #     "niche": post.niche,
    #     "keywords": post.matched_keywords,
    #     "url": post.full_url,
    #     "created_at": post.created_datetime,
    # })

    pass  # Implement your custom logic here
