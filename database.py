import sqlite3
import os
from typing import Set, Dict, Optional

class ArchiveDB:
    def __init__(self, db_path: str = "data/archive_progress.db"):
        self.db_path = db_path
        # Ensure the directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                url TEXT PRIMARY KEY,
                ia_bucket TEXT,
                ia_key TEXT,
                title TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration: add title column if it doesn't exist
        cursor.execute("PRAGMA table_info(uploads)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'title' not in columns:
            cursor.execute("ALTER TABLE uploads ADD COLUMN title TEXT")
        conn.commit()
        conn.close()

    def is_archived(self, url: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM uploads WHERE url = ?", (url,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def record_upload(self, url: str, bucket: str, key: str, title: str = ""):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO uploads (url, ia_bucket, ia_key, title)
            VALUES (?, ?, ?, ?)
        """, (url, bucket, key, title))
        conn.commit()
        conn.close()

    def get_archived_urls(self) -> Set[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM uploads")
        urls = {row[0] for row in cursor.fetchall()}
        conn.close()
        return urls

    def get_title_by_key(self, key: str) -> Optional[str]:
        """Get title for an article by its IA key."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM uploads WHERE ia_key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def get_titles_by_keys(self, keys: list) -> Dict[str, str]:
        """Get titles for multiple articles by their IA keys."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(keys))
        cursor.execute(f"SELECT ia_key, title FROM uploads WHERE ia_key IN ({placeholders})", keys)
        titles = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return titles
