import os
import sqlite3
import json
import logging
import asyncio
import urllib.request
import time
from typing import Optional, Dict, Any

logger = logging.getLogger("radio.quotes")

TURSO_URL = os.getenv("TURSO_URL", "https://counter-manhag.aws-eu-west-1.turso.io/v2/pipeline")
TURSO_TOKEN = os.getenv(
    "TURSO_TOKEN",
    "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJnaWQiOiI2MThiYjgzZi00MTFmLTQxNGItODk5NS04YTc0YjI3ZjUwNmMiLCJpYXQiOjE3ODk5ODIwMjMsImtpZCI6Ik5wZ1NZQ3FBWXhyand1Ml9ZZFFMcENQbWdsMzYwZGFCYXR6MzdwTzZxNlEiLCJyaWQiOiI5MmYyN2RmYi1mNGVlLTRkYTAtYTE5My0wZjcyNjNjYjVmZDcifQ.LgCB_CmOjBndjZnFcLOdDjl2uneSmWhPdvOVN5_2aLJzPGmC6CmL3JpJCHeZcfY2QLEa6fKpy9-nkYCPzSPlAQ"
)

class QuotesManager:
    def __init__(self, db_path: str = "/app/data/quotes.db"):
        self.db_path = db_path
        if not os.path.exists(os.path.dirname(self.db_path)):
            # fallback for host runner
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._sync_task: Optional[asyncio.Task] = None

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analytics (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
            """)
            # Initialize baseline all-time listeners if not exists
            cursor.execute("SELECT value FROM analytics WHERE key = 'all_time_listeners';")
            if not cursor.fetchone():
                cursor.execute("INSERT INTO analytics (key, value) VALUES ('all_time_listeners', 1420);")
            conn.commit()

    def sync_from_turso_sync(self) -> int:
        """Synchronously queries Turso pipeline API and populates local SQLite."""
        try:
            body = {
                "requests": [
                    {"type": "execute", "stmt": {"sql": "SELECT id, Name FROM quotes;"}}
                ]
            }
            req = urllib.request.Request(
                TURSO_URL,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {TURSO_TOKEN}",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = data.get("results", [])
            if not results or results[0].get("type") != "ok":
                logger.error(f"Turso response error: {data}")
                return 0

            rows = results[0]["response"]["result"]["rows"]
            count = 0
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for row in rows:
                    qid = row[0].get("value")
                    content = row[1].get("value")
                    if qid is not None and content:
                        cursor.execute(
                            "INSERT OR REPLACE INTO quotes (id, content) VALUES (?, ?);",
                            (int(qid), str(content))
                        )
                        count += 1
                cursor.execute("INSERT OR REPLACE INTO analytics (key, value) VALUES ('last_quotes_sync', ?);", (int(time.time()),))
                conn.commit()

            logger.info(f"Successfully synced {count} quotes from Turso into local SQLite")
            return count
        except Exception as e:
            logger.error(f"Failed to sync quotes from Turso: {e}")
            return 0

    async def sync_from_turso(self) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.sync_from_turso_sync)

    async def start_daily_sync_worker(self):
        """Runs initial sync if empty, then syncs every 24 hours."""
        count = self.get_quotes_count()
        if count == 0:
            logger.info("Local quotes database is empty. Triggering initial Turso sync...")
            await self.sync_from_turso()

        while True:
            try:
                # Sleep for 24 hours (86400s)
                await asyncio.sleep(86400)
                logger.info("Executing scheduled daily Turso quotes sync...")
                await self.sync_from_turso()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in daily quotes sync loop: {e}")
                await asyncio.sleep(300)

    def get_quotes_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) as count FROM quotes;")
            row = cursor.fetchone()
            return row["count"] if row else 0

    def get_random_quote(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, content FROM quotes ORDER BY RANDOM() LIMIT 1;")
            row = cursor.fetchone()
            total = self.get_quotes_count()
            if row:
                return {
                    "id": row["id"],
                    "content": row["content"],
                    "total_quotes": total
                }
            return None

    def increment_listener(self, station_id: Optional[str] = None):
        """Increments all-time listener counts for overall and per-station metrics."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE analytics SET value = value + 1 WHERE key = 'all_time_listeners';
                """)
                if station_id:
                    key = f"station_{station_id}_all_time"
                    cursor.execute("""
                        INSERT INTO analytics (key, value) VALUES (?, 1)
                        ON CONFLICT(key) DO UPDATE SET value = value + 1;
                    """, (key,))
                conn.commit()
        except Exception as e:
            logger.error(f"Error incrementing listener count: {e}")

    def get_all_time_listeners(self, station_id: Optional[str] = None) -> int:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if station_id:
                    cursor.execute("SELECT value FROM analytics WHERE key = ?;", (f"station_{station_id}_all_time",))
                    row = cursor.fetchone()
                    if row:
                        return row["value"]
                    # default baseline per station
                    return 240
                cursor.execute("SELECT value FROM analytics WHERE key = 'all_time_listeners';")
                row = cursor.fetchone()
                return row["value"] if row else 1420
        except Exception:
            return 1420
