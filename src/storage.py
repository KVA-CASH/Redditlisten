"""
Storage Module - SQLite database for persisting matched posts.
Enables historical analysis and trend detection.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager
from dataclasses import asdict

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "reddit_listener.db"


class PostStorage:
    """
    SQLite-based storage for matched Reddit posts.
    Handles persistence, querying, and trend analysis.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Main posts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS matched_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    selftext TEXT,
                    subreddit TEXT NOT NULL,
                    author TEXT,
                    url TEXT,
                    permalink TEXT,
                    full_url TEXT,
                    created_utc REAL,
                    niche TEXT NOT NULL,
                    score INTEGER DEFAULT 0,
                    num_comments INTEGER DEFAULT 0,
                    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Keywords table (many-to-many with posts)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS post_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    FOREIGN KEY (post_id) REFERENCES matched_posts(post_id),
                    UNIQUE(post_id, keyword)
                )
            """)

            # Indexes for fast queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_niche ON matched_posts(niche)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_subreddit ON matched_posts(subreddit)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_captured ON matched_posts(captured_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON post_keywords(keyword)")

            logger.info(f"Database initialized at {self.db_path}")

    def save_post(self, post) -> bool:
        """
        Save a matched post to the database.

        Args:
            post: MatchedPost object from listener module

        Returns:
            True if saved successfully, False if duplicate
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Insert post
                cursor.execute("""
                    INSERT OR IGNORE INTO matched_posts
                    (post_id, title, selftext, subreddit, author, url, permalink,
                     full_url, created_utc, niche, score, num_comments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    post.id,
                    post.title,
                    post.selftext,
                    post.subreddit,
                    post.author,
                    post.url,
                    post.permalink,
                    post.full_url,
                    post.created_utc,
                    post.niche,
                    post.score,
                    post.num_comments,
                ))

                if cursor.rowcount == 0:
                    logger.debug(f"Post {post.id} already exists in database")
                    return False

                # Insert keywords
                for keyword in post.matched_keywords:
                    cursor.execute("""
                        INSERT OR IGNORE INTO post_keywords (post_id, keyword)
                        VALUES (?, ?)
                    """, (post.id, keyword.lower()))

                logger.debug(f"Saved post {post.id} with {len(post.matched_keywords)} keywords")
                return True

        except Exception as e:
            logger.error(f"Failed to save post {post.id}: {e}")
            return False

    def get_total_posts(self) -> int:
        """Get total number of stored posts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM matched_posts")
            return cursor.fetchone()[0]

    def get_posts_by_niche(self, niche: str, limit: int = 50) -> List[Dict]:
        """Get recent posts for a specific niche."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM matched_posts
                WHERE niche = ?
                ORDER BY captured_at DESC
                LIMIT ?
            """, (niche, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_keyword_frequency(self, days: int = 7, limit: int = 20) -> List[Tuple[str, int]]:
        """
        Get most frequent keywords in the last N days.

        Returns:
            List of (keyword, count) tuples sorted by frequency
        """
        cutoff = datetime.now() - timedelta(days=days)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pk.keyword, COUNT(*) as count
                FROM post_keywords pk
                JOIN matched_posts mp ON pk.post_id = mp.post_id
                WHERE mp.captured_at >= ?
                GROUP BY pk.keyword
                ORDER BY count DESC
                LIMIT ?
            """, (cutoff.isoformat(), limit))
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_niche_frequency(self, days: int = 7) -> List[Tuple[str, int]]:
        """
        Get post counts per niche in the last N days.

        Returns:
            List of (niche, count) tuples sorted by frequency
        """
        cutoff = datetime.now() - timedelta(days=days)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT niche, COUNT(*) as count
                FROM matched_posts
                WHERE captured_at >= ?
                GROUP BY niche
                ORDER BY count DESC
            """, (cutoff.isoformat(),))
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_subreddit_frequency(self, days: int = 7, limit: int = 15) -> List[Tuple[str, int]]:
        """
        Get most active subreddits in the last N days.

        Returns:
            List of (subreddit, count) tuples sorted by frequency
        """
        cutoff = datetime.now() - timedelta(days=days)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT subreddit, COUNT(*) as count
                FROM matched_posts
                WHERE captured_at >= ?
                GROUP BY subreddit
                ORDER BY count DESC
                LIMIT ?
            """, (cutoff.isoformat(), limit))
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_trending_keywords(self,
                               recent_days: int = 1,
                               baseline_days: int = 7,
                               min_recent_count: int = 2) -> List[Dict]:
        """
        Find keywords trending up compared to baseline.

        Compares recent frequency to historical baseline to find
        keywords that are spiking in mentions.

        Returns:
            List of dicts with keyword, recent_count, baseline_avg, trend_score
        """
        recent_cutoff = datetime.now() - timedelta(days=recent_days)
        baseline_cutoff = datetime.now() - timedelta(days=baseline_days)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get recent counts
            cursor.execute("""
                SELECT pk.keyword, COUNT(*) as recent_count
                FROM post_keywords pk
                JOIN matched_posts mp ON pk.post_id = mp.post_id
                WHERE mp.captured_at >= ?
                GROUP BY pk.keyword
                HAVING recent_count >= ?
            """, (recent_cutoff.isoformat(), min_recent_count))
            recent_counts = {row[0]: row[1] for row in cursor.fetchall()}

            # Get baseline counts (excluding recent period)
            cursor.execute("""
                SELECT pk.keyword, COUNT(*) as baseline_count
                FROM post_keywords pk
                JOIN matched_posts mp ON pk.post_id = mp.post_id
                WHERE mp.captured_at >= ? AND mp.captured_at < ?
                GROUP BY pk.keyword
            """, (baseline_cutoff.isoformat(), recent_cutoff.isoformat()))
            baseline_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Calculate trend scores
        trending = []
        baseline_period = baseline_days - recent_days

        for keyword, recent_count in recent_counts.items():
            baseline_count = baseline_counts.get(keyword, 0)
            baseline_avg = baseline_count / baseline_period if baseline_period > 0 else 0
            recent_avg = recent_count / recent_days

            # Trend score: how many times higher than baseline
            if baseline_avg > 0:
                trend_score = recent_avg / baseline_avg
            else:
                trend_score = recent_avg * 10  # New keyword bonus

            trending.append({
                "keyword": keyword,
                "recent_count": recent_count,
                "baseline_avg": round(baseline_avg, 2),
                "trend_score": round(trend_score, 2),
            })

        # Sort by trend score
        trending.sort(key=lambda x: x["trend_score"], reverse=True)
        return trending[:10]

    def get_hourly_distribution(self, days: int = 7) -> Dict[int, int]:
        """
        Get post distribution by hour of day.

        Returns:
            Dict mapping hour (0-23) to post count
        """
        cutoff = datetime.now() - timedelta(days=days)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT strftime('%H', captured_at) as hour, COUNT(*) as count
                FROM matched_posts
                WHERE captured_at >= ?
                GROUP BY hour
                ORDER BY hour
            """, (cutoff.isoformat(),))
            return {int(row[0]): row[1] for row in cursor.fetchall()}

    def get_recent_posts(self, hours: int = 24, limit: int = 50) -> List[Dict]:
        """Get posts from the last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mp.*, GROUP_CONCAT(pk.keyword, ', ') as keywords
                FROM matched_posts mp
                LEFT JOIN post_keywords pk ON mp.post_id = pk.post_id
                WHERE mp.captured_at >= ?
                GROUP BY mp.post_id
                ORDER BY mp.captured_at DESC
                LIMIT ?
            """, (cutoff.isoformat(), limit))
            return [dict(row) for row in cursor.fetchall()]

    def cleanup_old_posts(self, days: int = 30) -> int:
        """
        Remove posts older than N days.

        Returns:
            Number of posts deleted
        """
        cutoff = datetime.now() - timedelta(days=days)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get post IDs to delete
            cursor.execute("""
                SELECT post_id FROM matched_posts WHERE captured_at < ?
            """, (cutoff.isoformat(),))
            post_ids = [row[0] for row in cursor.fetchall()]

            if not post_ids:
                return 0

            # Delete keywords first (foreign key)
            placeholders = ",".join("?" * len(post_ids))
            cursor.execute(f"""
                DELETE FROM post_keywords WHERE post_id IN ({placeholders})
            """, post_ids)

            # Delete posts
            cursor.execute(f"""
                DELETE FROM matched_posts WHERE post_id IN ({placeholders})
            """, post_ids)

            logger.info(f"Cleaned up {len(post_ids)} posts older than {days} days")
            return len(post_ids)
