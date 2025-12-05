"""
Storage Module - Database interface for persisting matched posts and pain points.
Supports both SQLite (local dev) and PostgreSQL (production).
"""

import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from contextlib import contextmanager

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

logger = logging.getLogger(__name__)

# Default database path (for SQLite)
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "reddit_listener.db"


class PostStorage:
    """
    Database storage for matched Reddit posts and analyzed pain points.
    Automatically selects between PostgreSQL (if DATABASE_URL set) and SQLite.
    """

    def __init__(self, db_path: Optional[Path] = None, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.use_postgres = bool(self.db_url) and HAS_POSTGRES
        
        if self.use_postgres:
            logger.info("Using PostgreSQL storage")
        else:
            self.db_path = db_path or DEFAULT_DB_PATH
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Using SQLite storage at {self.db_path}")
            
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        if self.use_postgres:
            try:
                conn = psycopg2.connect(self.db_url)
                try:
                    yield conn
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    raise e
                finally:
                    conn.close()
            except Exception as e:
                logger.error(f"PostgreSQL connection error: {e}")
                raise e
        else:
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

    def _get_placeholder(self) -> str:
        """Return variable placeholder based on DB type."""
        return "%s" if self.use_postgres else "?"

    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # PostgreSQL vs SQLite syntax differences
            serial_type = "SERIAL" if self.use_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
            text_type = "TEXT"
            timestamp_type = "TIMESTAMP" if self.use_postgres else "TEXT" # SQLite uses text/real for dates usually
            
            # 1. Matched Posts Table
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS matched_posts (
                    id {serial_type},
                    post_id {text_type} UNIQUE NOT NULL,
                    title {text_type} NOT NULL,
                    selftext {text_type},
                    subreddit {text_type} NOT NULL,
                    author {text_type},
                    url {text_type},
                    permalink {text_type},
                    full_url {text_type},
                    created_utc REAL,
                    niche {text_type} NOT NULL,
                    score INTEGER DEFAULT 0,
                    num_comments INTEGER DEFAULT 0,
                    captured_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Keywords Table
            # Note: SQLite doesn't support constraints in ADD COLUMN, but CREATE works
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS post_keywords (
                    id {serial_type},
                    post_id {text_type} NOT NULL,
                    keyword {text_type} NOT NULL,
                    UNIQUE(post_id, keyword)
                )
            """)

            # 3. Pain Points Table (New)
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS pain_points (
                    id {serial_type},
                    timestamp {timestamp_type},
                    niche {text_type},
                    subreddit {text_type},
                    keyword {text_type},
                    pain_score REAL,
                    severity {text_type},
                    context_snippet {text_type},
                    reddit_url {text_type},
                    post_title {text_type},
                    author {text_type}
                )
            """)

            # Indexes
            if self.use_postgres:
                # Postgres specific index creation if needed (idempotent usually requires IF NOT EXISTS)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_niche ON matched_posts(niche)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_captured ON matched_posts(captured_at)")
            else:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_niche ON matched_posts(niche)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_captured ON matched_posts(captured_at)")

            logger.info("Database initialized successfully")

    def save_post(self, post) -> bool:
        """Save a matched post to the database."""
        p = self._get_placeholder()
        query = f"""
            INSERT INTO matched_posts
            (post_id, title, selftext, subreddit, author, url, permalink,
             full_url, created_utc, niche, score, num_comments)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        if not self.use_postgres:
            query = query.replace("INSERT INTO", "INSERT OR IGNORE INTO")
        else:
            query += " ON CONFLICT (post_id) DO NOTHING"

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    post.id, post.title, post.selftext, post.subreddit, post.author,
                    post.url, post.permalink, post.full_url, post.created_utc,
                    post.niche, post.score, post.num_comments
                ))

                if cursor.rowcount == 0:
                    return False

                # Keywords
                kp = self._get_placeholder()
                k_query = f"INSERT INTO post_keywords (post_id, keyword) VALUES ({kp}, {kp})"
                if not self.use_postgres:
                    k_query = k_query.replace("INSERT INTO", "INSERT OR IGNORE INTO")
                else:
                    k_query += " ON CONFLICT (post_id, keyword) DO NOTHING"

                for keyword in post.matched_keywords:
                    cursor.execute(k_query, (post.id, keyword.lower()))

                return True
        except Exception as e:
            logger.error(f"Failed to save post {post.id}: {e}")
            return False

    def save_pain_point(self, pain_data: Dict[str, Any]) -> bool:
        """Save a pain point analysis result."""
        p = self._get_placeholder()
        query = f"""
            INSERT INTO pain_points
            (timestamp, niche, subreddit, keyword, pain_score, severity,
             context_snippet, reddit_url, post_title, author)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Ensure timestamp is datetime object or string
                ts = pain_data.get('timestamp')
                if isinstance(ts, str) and self.use_postgres:
                     # Postgres handles ISO strings well usually, but let's be safe
                     pass
                     
                cursor.execute(query, (
                    pain_data['timestamp'],
                    pain_data['niche'],
                    pain_data['subreddit'],
                    pain_data['keyword'],
                    pain_data['pain_score'],
                    pain_data['severity'],
                    pain_data['context_snippet'],
                    pain_data['reddit_url'],
                    pain_data['post_title'],
                    pain_data['author']
                ))
                return True
        except Exception as e:
            logger.error(f"Failed to save pain point: {e}")
            return False

    def get_all_pain_points(self, limit: int = 1000) -> List[Dict]:
        """Get pain points for export/display."""
        p = self._get_placeholder()
        query = f"SELECT * FROM pain_points ORDER BY timestamp DESC LIMIT {limit}"
        
        with self._get_connection() as conn:
            if self.use_postgres:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute(query)
                return [dict(row) for row in cursor.fetchall()]
            else:
                cursor = conn.cursor()
                cursor.execute(query)
                return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # ANALYTICS METHODS (Refactored for cross-DB compatibility)
    # =========================================================================

    def get_niche_frequency(self, days: int = 7) -> List[Tuple[str, int]]:
        cutoff = datetime.now() - timedelta(days=days)
        p = self._get_placeholder()
        
        # Postgres extract/date_trunc vs SQLite date functions are annoying.
        # Simplest way: pass ISO string and hope for best, usually works.
        
        query = f"""
            SELECT niche, COUNT(*) as count
            FROM matched_posts
            WHERE captured_at >= {p}
            GROUP BY niche
            ORDER BY count DESC
        """
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (cutoff.isoformat(),))
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_keyword_frequency(self, days: int = 7, limit: int = 20) -> List[Tuple[str, int]]:
        cutoff = datetime.now() - timedelta(days=days)
        p = self._get_placeholder()
        
        query = f"""
            SELECT pk.keyword, COUNT(*) as count
            FROM post_keywords pk
            JOIN matched_posts mp ON pk.post_id = mp.post_id
            WHERE mp.captured_at >= {p}
            GROUP BY pk.keyword
            ORDER BY count DESC
            LIMIT {limit}
        """
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (cutoff.isoformat(),))
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_subreddit_frequency(self, days: int = 7, limit: int = 15) -> List[Tuple[str, int]]:
        cutoff = datetime.now() - timedelta(days=days)
        p = self._get_placeholder()
        
        query = f"""
            SELECT subreddit, COUNT(*) as count
            FROM matched_posts
            WHERE captured_at >= {p}
            GROUP BY subreddit
            ORDER BY count DESC
            LIMIT {limit}
        """
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (cutoff.isoformat(),))
            return [(row[0], row[1]) for row in cursor.fetchall()]