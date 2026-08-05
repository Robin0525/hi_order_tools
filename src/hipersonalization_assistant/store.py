from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SubmissionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(submissions)").fetchall()
            }
            if "seller_id" in columns:
                connection.execute("ALTER TABLE submissions RENAME TO submissions_v1")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    order_id TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    order_title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (order_id, image_path)
                )
                """
            )
            if "seller_id" in columns:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO submissions
                        (order_id, image_path, order_title, status, message, updated_at)
                    SELECT order_id, image_path, order_title, status, message, updated_at
                    FROM submissions_v1
                    """
                )
                connection.execute("DROP TABLE submissions_v1")

    def record(
        self,
        *,
        order_id: str,
        image_path: Path,
        order_title: str,
        status: str,
        message: str = "",
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO submissions
                    (order_id, image_path, order_title, status, message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id, image_path) DO UPDATE SET
                    status = excluded.status,
                    message = excluded.message,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    str(image_path.resolve()),
                    order_title,
                    status,
                    message,
                    timestamp,
                ),
            )

    def was_successful(self, order_id: str, image_path: Path) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM submissions WHERE order_id = ? AND image_path = ?",
                (order_id, str(image_path.resolve())),
            ).fetchone()
        return bool(row and row[0] == "success")
