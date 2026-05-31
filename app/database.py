"""
Database setup — SQLite with auto-init.

Tables:
  events           — all detection pipeline events
  pos_transactions — POS transaction records loaded from CSV
"""

import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "data/store.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable JSON functions
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    # ── events table ──────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id   TEXT PRIMARY KEY,
            store_id   TEXT    NOT NULL,
            camera_id  TEXT,
            visitor_id TEXT    NOT NULL,
            event_type TEXT    NOT NULL,
            timestamp  TEXT    NOT NULL,
            zone_id    TEXT,
            dwell_ms   INTEGER DEFAULT 0,
            is_staff   BOOLEAN DEFAULT 0,
            confidence REAL    DEFAULT 0.0,
            metadata   TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_store_ts
        ON events (store_id, timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_visitor
        ON events (visitor_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_zone
        ON events (store_id, zone_id, timestamp)
    """)

    # ── pos_transactions table ────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_transactions (
            transaction_id   TEXT PRIMARY KEY,
            store_id         TEXT NOT NULL,
            timestamp        TEXT NOT NULL,
            basket_value_inr REAL DEFAULT 0.0
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pos_store_ts
        ON pos_transactions (store_id, timestamp)
    """)

    conn.commit()
    conn.close()


def load_pos_csv(csv_path: str) -> int:
    """
    Load POS transactions from CSV into the database.
    Idempotent — skips rows already present by transaction_id.

    Returns number of rows inserted.
    """
    import pandas as pd

    conn   = get_connection()
    cursor = conn.cursor()

    df = pd.read_csv(csv_path)

    # Normalise column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    inserted = 0
    for _, row in df.iterrows():
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO pos_transactions
                    (transaction_id, store_id, timestamp, basket_value_inr)
                VALUES (?, ?, ?, ?)
            """, (
                str(row.get("transaction_id", row.get("invoice_number", ""))),
                str(row.get("store_id", "STORE_BLR_002")),
                str(row.get("timestamp", row.get("order_date", ""))),
                float(row.get("basket_value_inr", row.get("total_amount", 0))),
            ))
            if cursor.rowcount == 1:
                inserted += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    return inserted
