"""
RSS-based Reddit Listener Module - Smart Pain Point Edition.

Polls Reddit's public RSS feeds and uses context-aware sentiment analysis
to identify genuine pain points (negative sentiment only).
"""

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import feedparser
import requests

from .config import (
    NICHES,
    USER_AGENT,
    REQUEST_TIMEOUT,
    SEEN_POSTS_FILE,
    MAX_SEEN_POSTS,
    NICHE_JITTER_MIN,
    NICHE_JITTER_MAX,
    build_rss_url,
    extract_keywords_from_query,
)
from .pain_analyzer import PainAnalyzer, AnalysisResult, PainPoint

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class RSSPost:
    """Data container for a Reddit post from RSS feed."""
    id: str
    title: str
    content: str  # Raw HTML content
    subreddit: str
    author: str
    link: str
    published: datetime
    niche: str
    matched_keywords: List[str] = field(default_factory=list)

    # Pain analysis results (populated after analysis)
    analysis_result: Optional[AnalysisResult] = None
    pain_points: List[PainPoint] = field(default_factory=list)
    has_pain: bool = False

    @property
    def full_url(self) -> str:
        return self.link

    @property
    def created_datetime(self) -> datetime:
        return self.published

    @property
    def most_severe_pain(self) -> Optional[PainPoint]:
        """Get the most severe pain point if any."""
        if self.analysis_result:
            return self.analysis_result.most_severe
        return None


# ============================================================================
# SEEN POSTS TRACKER
# ============================================================================

class SeenPostsTracker:
    """
    Tracks seen posts to prevent duplicate notifications.
    Persists to JSON file for durability across restarts.
    """

    def __init__(self, filepath: str = SEEN_POSTS_FILE, max_size: int = MAX_SEEN_POSTS):
        self.filepath = Path(filepath)
        self.max_size = max_size
        self._seen: Set[str] = set()
        self._load()

    def _load(self) -> None:
        """Load seen posts from file."""
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)
                    self._seen = set(data.get("posts", []))
                    logger.info(f"Loaded {len(self._seen)} seen posts from {self.filepath}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load seen posts: {e}")
                self._seen = set()
        else:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            self._seen = set()

    def save(self) -> None:
        """Save seen posts to file."""
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, 'w') as f:
                json.dump({
                    "posts": list(self._seen),
                    "updated_at": datetime.now().isoformat(),
                    "count": len(self._seen),
                }, f, indent=2)
            logger.debug(f"Saved {len(self._seen)} seen posts")
        except IOError as e:
            logger.error(f"Failed to save seen posts: {e}")

    def is_seen(self, post_id: str) -> bool:
        """Check if a post has been seen."""
        return post_id in self._seen

    def mark_seen(self, post_id: str) -> None:
        """Mark a post as seen."""
        self._seen.add(post_id)

        # Trim if over capacity
        if len(self._seen) > self.max_size:
            excess = len(self._seen) - self.max_size
            seen_list = list(self._seen)
            self._seen = set(seen_list[excess:])
            logger.info(f"Trimmed {excess} old posts from seen tracker")

    def count(self) -> int:
        return len(self._seen)


# ============================================================================
# RSS LISTENER - SMART PAIN DETECTION
# ============================================================================

class RSSListener:
    """
    RSS-based Reddit listener with context-aware pain point detection.

    Flow:
    1. Poll RSS feeds for each niche
    2. For new posts, extract keywords
    3. Run sentiment analysis on context windows
    4. Only trigger callback for NEGATIVE sentiment matches
    """

    def __init__(
        self,
        on_pain_point: Callable[[RSSPost], None],
        on_neutral_match: Optional[Callable[[RSSPost], None]] = None
    ):
        """
        Initialize the RSS listener.

        Args:
            on_pain_point: Callback for posts with NEGATIVE pain points
            on_neutral_match: Optional callback for neutral/positive matches (for stats)
        """
        self.on_pain_point = on_pain_point
        self.on_neutral_match = on_neutral_match
        self.seen_tracker = SeenPostsTracker()
        self.pain_analyzer = PainAnalyzer()
        self._running = False
        self._session = self._create_session()

        # Statistics
        self._poll_count = 0
        self._total_posts_seen = 0
        self._pain_points_found = 0
        self._neutral_filtered = 0

    def _create_session(self) -> requests.Session:
        """Create a requests session with browser-like headers."""
        session = requests.Session()

        # Rotate through different user agents to avoid detection
        user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        ]

        session.headers.update({
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        })
        return session

    def _rotate_user_agent(self) -> None:
        """Rotate user agent to avoid detection."""
        user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        ]
        self._session.headers['User-Agent'] = random.choice(user_agents)

    def _fetch_feed(self, url: str, retry_count: int = 3) -> Optional[feedparser.FeedParserDict]:
        """Fetch and parse an RSS feed with retry logic."""
        for attempt in range(retry_count):
            try:
                # Rotate user agent on each attempt
                self._rotate_user_agent()

                # Add small random delay to avoid rate limiting
                if attempt > 0:
                    delay = random.uniform(2, 5) * (attempt + 1)
                    logger.debug(f"Retry {attempt + 1}/{retry_count} after {delay:.1f}s...")
                    time.sleep(delay)

                response = self._session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()

                feed = feedparser.parse(response.content)

                if feed.bozo and feed.bozo_exception:
                    logger.warning(f"Feed parse warning: {feed.bozo_exception}")

                return feed

            except requests.exceptions.RequestException as e:
                if attempt == retry_count - 1:
                    logger.error(f"Failed to fetch feed after {retry_count} attempts: {e}")
                else:
                    logger.debug(f"Attempt {attempt + 1} failed: {e}")

        return None

    def _extract_post_id(self, entry: dict) -> str:
        """Extract unique post ID from RSS entry."""
        if 'id' in entry:
            match = re.search(r't3_(\w+)', entry['id'])
            if match:
                return match.group(1)
            return entry['id']

        if 'link' in entry:
            match = re.search(r'/comments/(\w+)/', entry['link'])
            if match:
                return match.group(1)

        return str(hash(entry.get('link', entry.get('title', ''))))

    def _extract_subreddit(self, entry: dict) -> str:
        """Extract subreddit name from RSS entry."""
        link = entry.get('link', '')
        match = re.search(r'/r/(\w+)/', link)
        if match:
            return match.group(1)
        return "unknown"

    def _extract_author(self, entry: dict) -> str:
        """Extract author from RSS entry."""
        if 'author' in entry:
            author = entry['author']
            return author.replace('/u/', '').strip()

        if 'author_detail' in entry:
            return entry['author_detail'].get('name', 'unknown')

        return "unknown"

    def _parse_published(self, entry: dict) -> datetime:
        """Parse published date from RSS entry."""
        if 'published_parsed' in entry and entry['published_parsed']:
            try:
                return datetime(*entry['published_parsed'][:6])
            except (TypeError, ValueError):
                pass

        if 'updated_parsed' in entry and entry['updated_parsed']:
            try:
                return datetime(*entry['updated_parsed'][:6])
            except (TypeError, ValueError):
                pass

        return datetime.now()

    def _get_raw_content(self, entry: dict) -> str:
        """Get raw HTML content from RSS entry."""
        if 'content' in entry and entry['content']:
            return entry['content'][0].get('value', '')
        elif 'summary' in entry:
            return entry['summary']
        return ""

    def _process_entry(self, entry: dict, niche_name: str) -> Optional[RSSPost]:
        """
        Process a single RSS entry with pain point analysis.

        Args:
            entry: RSS feed entry
            niche_name: Name of the niche

        Returns:
            RSSPost if it's new and contains pain points, None otherwise
        """
        post_id = self._extract_post_id(entry)

        # Skip if already seen
        if self.seen_tracker.is_seen(post_id):
            return None

        # Mark as seen immediately
        self.seen_tracker.mark_seen(post_id)
        self._total_posts_seen += 1

        # Check post age - skip posts older than 7 days
        published = self._parse_published(entry)
        max_age = timedelta(days=7)
        if datetime.now() - published > max_age:
            logger.debug(f"Skipping old post from {published.date()}")
            return None

        # Extract data
        title = entry.get('title', '')
        raw_content = self._get_raw_content(entry)
        subreddit = self._extract_subreddit(entry)
        author = self._extract_author(entry)
        link = entry.get('link', '')
        published = self._parse_published(entry)

        # Get keywords for this niche
        niche_data = NICHES.get(niche_name, {})
        search_query = niche_data.get("search_query", "")
        keywords = extract_keywords_from_query(search_query)

        # Pre-filter: Check if any keyword appears in title or content
        # (Since we're using /new.rss instead of search, we filter client-side)
        combined_text = f"{title} {raw_content}".lower()
        has_keyword_match = any(kw.lower() in combined_text for kw in keywords)
        if not has_keyword_match:
            return None  # Skip posts without keyword matches

        # Run pain point analysis
        analysis_result = self.pain_analyzer.analyze_post(
            title=title,
            content=raw_content,
            keywords=keywords
        )

        # Create post object
        post = RSSPost(
            id=post_id,
            title=title,
            content=raw_content,
            subreddit=subreddit,
            author=author,
            link=link,
            published=published,
            niche=niche_name,
            matched_keywords=[pp.keyword for pp in analysis_result.pain_points],
            analysis_result=analysis_result,
            pain_points=analysis_result.pain_points,
            has_pain=analysis_result.has_pain_points
        )

        # Check if we have actual pain points (negative sentiment)
        if analysis_result.has_pain_points:
            self._pain_points_found += 1
            logger.info(
                f"🔴 Pain point found in {niche_name}: "
                f"{len(analysis_result.pain_points)} negative matches"
            )
            return post
        else:
            # Check if there were any keyword matches at all
            keyword_matches = self.pain_analyzer.find_keyword_in_sentences(
                analysis_result.sentences,
                keywords[0] if keywords else ""
            )
            if keyword_matches or analysis_result.overall_sentiment != 0:
                self._neutral_filtered += 1
                logger.debug(
                    f"Filtered neutral/positive post: {title[:50]}... "
                    f"(sentiment: {analysis_result.overall_sentiment:.3f})"
                )
                # Optionally notify about neutral matches
                if self.on_neutral_match:
                    self.on_neutral_match(post)

            return None

    def poll_niche(self, niche_name: str) -> List[RSSPost]:
        """
        Poll a single niche by iterating over each subreddit individually.

        Args:
            niche_name: Name of the niche to poll

        Returns:
            List of posts with pain points
        """
        niche_data = NICHES.get(niche_name)
        if not niche_data:
            logger.warning(f"Unknown niche: {niche_name}")
            return []

        subreddits = niche_data["subreddits"]
        pain_posts = []

        for subreddit in subreddits:
            if not self._running:
                break

            url = build_rss_url(subreddit)
            logger.debug(f"Polling r/{subreddit} for {niche_name}...")

            feed = self._fetch_feed(url)
            if not feed or not feed.entries:
                logger.debug(f"No entries found for r/{subreddit}")
                continue

            for entry in feed.entries:
                post = self._process_entry(entry, niche_name)
                if post and post.has_pain:
                    pain_posts.append(post)

            # Small delay between subreddits to be polite
            if self._running and subreddit != subreddits[-1]:
                time.sleep(random.uniform(1, 3))

        if pain_posts:
            logger.info(
                f"Found {len(pain_posts)} posts with pain points in {niche_name}"
            )

        return pain_posts

    def poll_all_niches(self) -> List[RSSPost]:
        """
        Poll all niches with jitter between each.

        Returns:
            List of all posts with pain points
        """
        self._poll_count += 1
        all_pain_posts = []

        for niche_name in NICHES.keys():
            if not self._running:
                break

            posts = self.poll_niche(niche_name)
            all_pain_posts.extend(posts)

            # Notify for each pain post
            for post in posts:
                try:
                    self.on_pain_point(post)
                except Exception as e:
                    logger.error(f"Error in on_pain_point callback: {e}")

            # Add jitter between niche polls
            if self._running and niche_name != list(NICHES.keys())[-1]:
                jitter = random.uniform(NICHE_JITTER_MIN, NICHE_JITTER_MAX)
                logger.debug(f"Sleeping {jitter:.1f}s before next niche...")
                time.sleep(jitter)

        # Save seen posts after each full poll cycle
        self.seen_tracker.save()

        return all_pain_posts

    def start(self, poll_interval_min: int, poll_interval_max: int) -> None:
        """
        Start the polling loop.

        Args:
            poll_interval_min: Minimum seconds between poll cycles
            poll_interval_max: Maximum seconds between poll cycles
        """
        logger.info("Starting Smart Pain Listener...")
        self._running = True

        while self._running:
            try:
                start_time = time.time()

                # Poll all niches
                pain_posts = self.poll_all_niches()

                elapsed = time.time() - start_time
                logger.info(
                    f"Poll #{self._poll_count} complete: "
                    f"{len(pain_posts)} pain posts, "
                    f"{self._neutral_filtered} filtered, "
                    f"{self.seen_tracker.count()} total seen, "
                    f"took {elapsed:.1f}s"
                )

                if not self._running:
                    break

                # Sleep with random jitter before next cycle
                sleep_time = random.uniform(poll_interval_min, poll_interval_max)
                logger.info(f"Next poll in {sleep_time/60:.1f} minutes...")

                # Sleep in small increments for graceful shutdown
                sleep_end = time.time() + sleep_time
                while self._running and time.time() < sleep_end:
                    time.sleep(min(5, sleep_end - time.time()))

            except Exception as e:
                logger.exception(f"Error in poll cycle: {e}")
                if self._running:
                    time.sleep(60)

        logger.info("Smart Pain Listener stopped.")

    def stop(self) -> None:
        """Signal the listener to stop."""
        logger.info("Stop signal received...")
        self._running = False
        self.seen_tracker.save()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def poll_count(self) -> int:
        return self._poll_count

    @property
    def pain_points_found(self) -> int:
        return self._pain_points_found

    @property
    def neutral_filtered(self) -> int:
        return self._neutral_filtered

    @property
    def seen_count(self) -> int:
        return self.seen_tracker.count()

    @property
    def total_posts_seen(self) -> int:
        return self._total_posts_seen
