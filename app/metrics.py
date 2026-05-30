from app.database import get_connection

def get_store_metrics(store_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(DISTINCT visitor_id) FROM events WHERE store_id=?",
        (store_id,)
    )
    visitors = cursor.fetchone()[0]

    cursor.execute(
        "SELECT AVG(dwell_ms) FROM events WHERE store_id=?",
        (store_id,)
    )
    avg_dwell = cursor.fetchone()[0]

    conn.close()

    return {
        "store_id": store_id,
        "unique_visitors": visitors,
        "avg_dwell_ms": avg_dwell or 0
    }