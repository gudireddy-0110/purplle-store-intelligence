from app.database import get_connection

def get_store_metrics(store_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(DISTINCT visitor_id) FROM events WHERE store_id=? AND is_staff=0",
        (store_id,)
    )
    unique_visitors = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT AVG(dwell_ms) FROM events WHERE store_id=? AND is_staff=0",
        (store_id,)
    )
    avg_dwell = cursor.fetchone()[0] or 0

    conn.close()

    return {
        "store_id": store_id,
        "unique_visitors": unique_visitors,
        "avg_dwell_ms": round(avg_dwell, 2)
    }