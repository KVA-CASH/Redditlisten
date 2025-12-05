"""
Configuration module for Reddit Listener Bot (RSS-based).
Handles niche definitions, search queries, and app settings.
"""

import os
from dataclasses import dataclass
from typing import Dict, List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ============================================================================
# NICHE CONFIGURATION - RSS Search Queries
# ============================================================================

# Each niche now has a list of individual subreddits to avoid 403 blocks
NICHES: Dict[str, Dict[str, any]] = {
    "Sweaty_Startup": {
        "subreddits": ["sweatystartup", "smallbusiness", "Entrepreneur"],
        "search_query": '(paperwork OR "scheduling nightmare" OR "invoicing mess" OR "jobber" OR "no show")'
    },
    "Agency_Owners": {
        "subreddits": ["freelance", "webdev", "marketing"],
        "search_query": '("client onboarding" OR "collecting assets" OR "scope creep" OR "chasing clients" OR "getting paid")'
    },
    "Ecommerce_Ops": {
        "subreddits": ["shopify", "ecommerce", "dropship"],
        "search_query": '("too many apps" OR "inventory sync" OR "broken theme" OR "shipping rates" OR "sync error")'
    },
    "Content_Creators": {
        "subreddits": ["NewTubers", "Twitch", "youtubers"],
        "search_query": '("editing takes forever" OR "editor expensive" OR "premiere crash" OR "captioning time" OR "boring editing")'
    },
    "Recruiters": {
        "subreddits": ["recruiting", "humanresources", "recruitinghell"],
        "search_query": '("clunky ats" OR "resume parsing" OR "manual entry" OR "candidate tracking" OR "sourcing hard")'
    }
}


# ============================================================================
# RSS SETTINGS
# ============================================================================

# Polling interval in seconds (5-10 minutes recommended)
POLL_INTERVAL_MIN: int = int(os.getenv("POLL_INTERVAL_MIN", "300"))  # 5 minutes
POLL_INTERVAL_MAX: int = int(os.getenv("POLL_INTERVAL_MAX", "600"))  # 10 minutes

# Jitter between niche polls (seconds)
NICHE_JITTER_MIN: int = int(os.getenv("NICHE_JITTER_MIN", "5"))
NICHE_JITTER_MAX: int = int(os.getenv("NICHE_JITTER_MAX", "15"))

# User agent to avoid being blocked
USER_AGENT: str = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Request timeout
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))


# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

# File to store seen post IDs
SEEN_POSTS_FILE: str = os.getenv("SEEN_POSTS_FILE", "data/seen_posts.json")

# Maximum number of seen posts to keep in memory (prevents unbounded growth)
MAX_SEEN_POSTS: int = int(os.getenv("MAX_SEEN_POSTS", "10000"))

# Database path (for analytics)
DB_PATH: str = os.getenv("DB_PATH", "data/reddit_listener.db")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", "logs/reddit_listener.log")


# ============================================================================
# NOTIFICATION SETTINGS
# ============================================================================

@dataclass
class NotificationConfig:
    """Notification settings container."""
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""
    enable_console: bool = True
    enable_discord: bool = False
    enable_slack: bool = False


def get_notification_config() -> NotificationConfig:
    """Load notification settings from environment."""
    return NotificationConfig(
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        enable_console=os.getenv("ENABLE_CONSOLE_NOTIFICATIONS", "true").lower() == "true",
        enable_discord=os.getenv("ENABLE_DISCORD_NOTIFICATIONS", "false").lower() == "true",
        enable_slack=os.getenv("ENABLE_SLACK_NOTIFICATIONS", "false").lower() == "true",
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def build_rss_url(subreddit: str) -> str:
    """
    Build the RSS feed URL for a single subreddit's new posts.

    Note: Uses old.reddit.com which is more lenient with RSS feeds.

    Args:
        subreddit: Single subreddit name (e.g., "shopify")

    Returns:
        RSS URL for new posts in the subreddit
    """
    return f"https://old.reddit.com/r/{subreddit}/new/.rss?limit=25"


def get_all_rss_urls() -> Dict[str, List[str]]:
    """
    Get all RSS URLs for all niches (one URL per subreddit).

    Returns:
        Dict mapping niche name to list of RSS URLs
    """
    return {
        niche_name: [build_rss_url(sub) for sub in niche_data["subreddits"]]
        for niche_name, niche_data in NICHES.items()
    }


def extract_keywords_from_query(search_query: str) -> List[str]:
    """
    Extract individual keywords/phrases from a search query.

    Args:
        search_query: The search query string

    Returns:
        List of keywords/phrases
    """
    import re

    # Find quoted phrases and unquoted words
    quoted = re.findall(r'"([^"]+)"', search_query)

    # Also find OR-separated single words
    unquoted = re.findall(r'\b([a-zA-Z]+)\b', search_query)
    unquoted = [w for w in unquoted if w.upper() != 'OR']

    return quoted + unquoted


def validate_config() -> List[str]:
    """
    Validate configuration and return list of any issues found.
    """
    issues = []

    if POLL_INTERVAL_MIN < 60:
        issues.append("POLL_INTERVAL_MIN should be at least 60 seconds to avoid rate limiting")

    if POLL_INTERVAL_MAX < POLL_INTERVAL_MIN:
        issues.append("POLL_INTERVAL_MAX should be greater than POLL_INTERVAL_MIN")

    notif = get_notification_config()
    if notif.enable_discord and not notif.discord_webhook_url:
        issues.append("ENABLE_DISCORD_NOTIFICATIONS is true but DISCORD_WEBHOOK_URL is not set")
    if notif.enable_slack and not notif.slack_webhook_url:
        issues.append("ENABLE_SLACK_NOTIFICATIONS is true but SLACK_WEBHOOK_URL is not set")

    return issues
