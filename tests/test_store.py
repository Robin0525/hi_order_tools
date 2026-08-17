from pathlib import Path
import sqlite3

from hipersonalization_assistant.store import SubmissionStore


def test_store_records_and_updates_status(tmp_path: Path):
    store = SubmissionStore(tmp_path / "history.db")
    image = tmp_path / "image.png"
    image.write_bytes(b"image")

    store.record(
        order_id="123",
        image_path=image,
        order_title="Batch",
        status="failed",
        message="temporary",
    )
    assert not store.was_successful("123", image)

    store.record(
        order_id="123",
        image_path=image,
        order_title="Batch",
        status="success",
    )
    assert store.was_successful("123", image)


def test_store_distinguishes_same_image_with_different_submission_configuration(
    tmp_path: Path,
):
    store = SubmissionStore(tmp_path / "history.db")
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    store.record(
        order_id="123",
        image_path=image,
        type_option="A+001",
        quantity=1,
        product_code="Order A",
        order_title="Order A",
        status="success",
    )

    assert store.was_successful(
        "123",
        image,
        type_option="A+001",
        quantity=1,
        product_code="Order A",
    )
    assert not store.was_successful(
        "123",
        image,
        type_option="A+002",
        quantity=1,
        product_code="Order A",
    )


def test_store_migrates_old_seller_id_column(tmp_path: Path):
    database = tmp_path / "history.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE submissions (
                order_id TEXT NOT NULL,
                image_path TEXT NOT NULL,
                seller_id TEXT NOT NULL,
                order_title TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (order_id, image_path)
            )
            """
        )
        connection.execute(
            "INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("1", "image.png", "224", "Old", "success", "", "now"),
        )

    SubmissionStore(database)

    with sqlite3.connect(database) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(submissions)")]
        row = connection.execute("SELECT order_id, order_title, status FROM submissions").fetchone()
    assert "seller_id" not in columns
    assert {"type_option", "quantity", "product_code"}.issubset(columns)
    assert row == ("1", "Old", "success")
