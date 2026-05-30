import sqlite3

DB_NAME = "store.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        store_id TEXT,
        camera_id TEXT,
        visitor_id TEXT,
        event_type TEXT,
        timestamp TEXT,
        zone_id TEXT,
        dwell_ms INTEGER,
        is_staff BOOLEAN,
        confidence REAL
    )
    """)

    conn.commit()
    conn.close()