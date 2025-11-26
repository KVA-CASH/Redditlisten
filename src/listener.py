"""
Core Reddit Listener Module.
Handles PRAW stream connections with filtering and deduplication.
"""

import time
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Set
from collections import OrderedDict

import praw
from praw.models import Submission
from prawcore.exceptions import (
    ServerError,
    RequestException,
    ResponseException,
)

from .config import (
    get_reddit_credentials,
    get_all_subreddits,
    find_matching_niche,
    POST_COOLDOWN_SECONDS,
    MAX_CACHE_SIZE,
    RECONNECT_DELAY_SECONDS,
    MAX_RECONNECT_ATTEMPTS,
)

logger = logging.getLogger(__name__)


@dataclass
class MatchedPost:
    """Data container for a matched Reddit post."""
    id: str
    title: str
    selftext: str
    subreddit: str
    author: str
    url: str
    permalink: str
    created_utc: float
    niche: str
    matched_keywords: list
    score: int
    num_comments: int

    @property
    def full_url(self) -> str:
        return f"https://reddit.com{self.permalink}"

    @property
    def created_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.created_utc)

    @property
    def combined_text(self) -> str:
        """Combined title and body for keyword matching."""
        return f"{self.title} {self.selftext}".lower()


class PostCache:
    """
    LRU cache for tracking seen posts to prevent duplicate notifications.
    Uses OrderedDict for O(1) operations with automatic size limiting.
    """

    def __init__(self, max_size: int = MAX_CACHE_SIZE, cooldown_seconds: int = POST_COOLDOWN_SECONDS):
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size
        self._cooldown = cooldown_seconds

    def is_seen(self, post_id: str) -> bool:
        """Check if post was recently seen (within cooldown period)."""
        if post_id not in self._cache:
            return False

        seen_time = self._cache[post_id]
        if time.time() - seen_time > self._cooldown:
            # Cooldown expired, treat as unseen
            del self._cache[post_id]
            return False

        return True

    def mark_seen(self, post_id: str) -> None:
        """Mark a post as seen with current timestamp."""
        # Move to end if exists (LRU update)
        if post_id in self._cache:
            self._cache.move_to_end(post_id)

        self._cache[post_id] = time.time()

        # Evict oldest if over capacity
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()


class RedditListener:
    """
    Main Reddit listener class.
    Handles stream connection, filtering, and callback dispatch.
    """

    # Authors to always ignore
    IGNORED_AUTHORS: Set[str] = {"AutoModerator", "[deleted]", "None"}

    def __init__(self, on_match: Callable[[MatchedPost], None]):
        """
        Initialize the listener.

        Args:
            on_match: Callback function to invoke when a matching post is found.
        """
        self.on_match = on_match
        self.cache = PostCache()
        self.reddit: Optional[praw.Reddit] = None
        self._running = False
        self._reconnect_count = 0

    def _init_reddit(self) -> praw.Reddit:
        """Initialize PRAW Reddit instance."""
        creds = get_reddit_credentials()

        # Use read-only mode if no username/password provided
        if creds.username and creds.password:
            return praw.Reddit(
                client_id=creds.client_id,
                client_secret=creds.client_secret,
                user_agent=creds.user_agent,
                username=creds.username,
                password=creds.password,
            )
        else:
            return praw.Reddit(
                client_id=creds.client_id,
                client_secret=creds.client_secret,
                user_agent=creds.user_agent,
            )

    def _should_skip_post(self, submission: Submission) -> tuple[bool, str]:
        """
        Determine if a post should be skipped.

        Returns:
            Tuple of (should_skip, reason)
        """
        # Skip if already seen
        if self.cache.is_seen(submission.id):
            return True, "duplicate"

        # Skip AutoModerator and deleted posts
        author_name = str(submission.author) if submission.author else "[deleted]"
        if author_name in self.IGNORED_AUTHORS:
            return True, f"ignored_author:{author_name}"

        # Skip stickied/pinned posts
        if getattr(submission, 'stickied', False):
            return True, "stickied"

        # Skip if post is too old (more than 1 hour) - for initial stream catchup
        post_age = time.time() - submission.created_utc
        if post_age > 3600:  # 1 hour
            return True, "too_old"

        return False, ""

    def _process_submission(self, submission: Submission) -> Optional[MatchedPost]:
        """
        Process a single submission and return MatchedPost if it matches criteria.
        """
        # Check skip conditions
        should_skip, reason = self._should_skip_post(submission)
        if should_skip:
            logger.debug(f"Skipping post {submission.id}: {reason}")
            return None

        # Mark as seen immediately to prevent duplicates
        self.cache.mark_seen(submission.id)

        # Get combined text for matching
        title = submission.title or ""
        selftext = submission.selftext or ""
        combined_text = f"{title} {selftext}"
        subreddit_name = str(submission.subreddit)

        # Find matching niche and keywords
        niche, matched_keywords = find_matching_niche(subreddit_name, combined_text)

        if not matched_keywords:
            logger.debug(f"No keyword match for post {submission.id} in r/{subreddit_name}")
            return None

        # Build MatchedPost object
        author_name = str(submission.author) if submission.author else "[deleted]"

        return MatchedPost(
            id=submission.id,
            title=title,
            selftext=selftext[:500] + "..." if len(selftext) > 500 else selftext,
            subreddit=subreddit_name,
            author=author_name,
            url=submission.url,
            permalink=submission.permalink,
            created_utc=submission.created_utc,
            niche=niche,
            matched_keywords=matched_keywords,
            score=submission.score,
            num_comments=submission.num_comments,
        )

    def _stream_with_retry(self):
        """
        Generator that yields submissions with automatic retry on errors.
        """
        while self._running and self._reconnect_count < MAX_RECONNECT_ATTEMPTS:
            try:
                # Get combined multi-reddit string
                multi_subreddit = get_all_subreddits()
                logger.info(f"Connecting to stream: r/{multi_subreddit}")

                subreddit = self.reddit.subreddit(multi_subreddit)

                # Skip existing posts on first connect (skip_existing=True)
                for submission in subreddit.stream.submissions(skip_existing=True, pause_after=-1):
                    if not self._running:
                        break

                    if submission is None:
                        # pause_after=-1 returns None when no new posts
                        # This prevents blocking and allows checking _running flag
                        continue

                    self._reconnect_count = 0  # Reset on successful yield
                    yield submission

            except (ServerError, RequestException, ResponseException) as e:
                self._reconnect_count += 1
                logger.warning(
                    f"Stream error (attempt {self._reconnect_count}/{MAX_RECONNECT_ATTEMPTS}): {e}"
                )
                if self._reconnect_count < MAX_RECONNECT_ATTEMPTS:
                    logger.info(f"Reconnecting in {RECONNECT_DELAY_SECONDS} seconds...")
                    time.sleep(RECONNECT_DELAY_SECONDS)
                else:
                    logger.error("Max reconnection attempts reached. Stopping listener.")
                    break

            except Exception as e:
                logger.exception(f"Unexpected error in stream: {e}")
                self._reconnect_count += 1
                if self._reconnect_count < MAX_RECONNECT_ATTEMPTS:
                    time.sleep(RECONNECT_DELAY_SECONDS)
                else:
                    break

    def start(self) -> None:
        """Start the listener. Blocks until stop() is called."""
        logger.info("Starting Reddit Listener...")

        self.reddit = self._init_reddit()
        self._running = True
        self._reconnect_count = 0

        logger.info(f"Connected to Reddit as read-only: {self.reddit.read_only}")
        logger.info(f"Monitoring {len(get_all_subreddits().split('+'))} subreddits")

        for submission in self._stream_with_retry():
            if not self._running:
                break

            try:
                matched_post = self._process_submission(submission)
                if matched_post:
                    logger.info(
                        f"MATCH FOUND: [{matched_post.niche}] r/{matched_post.subreddit} - "
                        f"Keywords: {matched_post.matched_keywords}"
                    )
                    self.on_match(matched_post)

            except Exception as e:
                logger.exception(f"Error processing submission {submission.id}: {e}")

        logger.info("Reddit Listener stopped.")

    def stop(self) -> None:
        """Signal the listener to stop."""
        logger.info("Stop signal received...")
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cache_size(self) -> int:
        return self.cache.size()
