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
            legacy_table = bool(columns) and not {
                "type_option",
                "quantity",
                "product_code",
            }.issubset(columns)
            if legacy_table:
                connection.execute(
                    "ALTER TABLE submissions RENAME TO submissions_legacy_configuration"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    order_id TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    type_option TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    product_code TEXT NOT NULL,
                    order_title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        order_id, image_path, type_option, quantity, product_code
                    )
                )
                """
            )
            if legacy_table:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO submissions
                        (order_id, image_path, type_option, quantity, product_code,
                         order_title, status, message, updated_at)
                    SELECT order_id, image_path, '', 0, '', order_title, status, message, updated_at
                    FROM submissions_legacy_configuration
                    """
                )
                connection.execute("DROP TABLE submissions_legacy_configuration")

    def record(
        self,
        *,
        order_id: str,
        image_path: Path,
        type_option: str = "",
        quantity: int = 0,
        product_code: str = "",
        order_title: str,
        status: str,
        message: str = "",
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO submissions
                    (order_id, image_path, type_option, quantity, product_code,
                     order_title, status, message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id, image_path, type_option, quantity, product_code)
                DO UPDATE SET
                    status = excluded.status,
                    message = excluded.message,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    str(image_path.resolve()),
                    type_option,
                    quantity,
                    product_code,
                    order_title,
                    status,
                    message,
                    timestamp,
                ),
            )

    def was_successful(
        self,
        order_id: str,
        image_path: Path,
        *,
        type_option: str = "",
        quantity: int = 0,
        product_code: str = "",
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status FROM submissions
                WHERE order_id = ? AND image_path = ? AND type_option = ?
                  AND quantity = ? AND product_code = ?
                """,
                (
                    order_id,
                    str(image_path.resolve()),
                    type_option,
                    quantity,
                    product_code,
                ),
            ).fetchone()
        return bool(row and row[0] == "success")
