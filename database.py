import sqlite3
import os
from typing import Set

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
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def is_archived(self, url: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM uploads WHERE url = ?", (url,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def record_upload(self, url: str, bucket: str, key: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO uploads (url, ia_bucket, ia_key)
            VALUES (?, ?, ?)
        """, (url, bucket, key))
        conn.commit()
        conn.close()

    def get_archived_urls(self) -> Set[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM uploads")
        urls = {row[0] for row in cursor.fetchall()}
        conn.close()
        return urls
