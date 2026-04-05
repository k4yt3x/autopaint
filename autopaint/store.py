"""SQLite persistence for session cooldown times and learned rate.

Allows the program to resume after Ctrl+C without re-discovering cooldown
windows by trial and error.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

DEFAULT_DB_PATH = Path("data/autopaint.db")


class Store:
    """Thread-safe SQLite store for cross-restart state."""

    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._migrate()

        logger.debug("Store opened at {}", path)

    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS session_cooldowns (
                    session_cookie TEXT PRIMARY KEY,
                    reset_at       TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS kv (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    # ------------------------------------------------------------------
    # Session cooldowns
    # ------------------------------------------------------------------

    def set_cooldown(self, session_cookie: str, reset_at: str) -> None:
        """Record when a session's vote budget resets (ISO 8601 UTC)."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO session_cooldowns (session_cookie, reset_at) VALUES (?, ?)",
                (session_cookie, reset_at),
            )
            self._conn.commit()

    def get_cooldown_remaining(self, session_cookie: str) -> float:
        """Return seconds until this session's cooldown expires, or 0."""
        with self._lock:
            row = self._conn.execute(
                "SELECT reset_at FROM session_cooldowns WHERE session_cookie = ?",
                (session_cookie,),
            ).fetchone()

        if row is None:
            return 0.0

        try:
            reset_time = datetime.fromisoformat(row[0])
            remaining = (reset_time - datetime.now(timezone.utc)).total_seconds()
            return max(remaining, 0.0)
        except (ValueError, TypeError):
            return 0.0

    def clear_cooldown(self, session_cookie: str) -> None:
        """Remove a session's cooldown entry."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM session_cooldowns WHERE session_cookie = ?",
                (session_cookie,),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Key-value (learned rate, etc.)
    # ------------------------------------------------------------------

    def set_value(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                (key, value),
            )
            self._conn.commit()

    def get_value(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()

        return row[0] if row else default

    def close(self) -> None:
        self._conn.close()
