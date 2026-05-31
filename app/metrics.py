"""
Store metrics — real-time analytics for a single store.

Returns:
  - unique_visitors (staff excluded)
  - conversion_rate (POS 5-min window correlation)
  - avg_dwell_per_zone
  - queue_depth (current billing zone depth)
  - abandonment_rate
"""

from app.database import get_connection


def get_store_metrics(store_id: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    # ── unique visitors today (staff excluded) ────────────────────────────────
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id   = ?
          AND event_type = 'ENTRY'
          AND is_staff   = 0
    """, (store_id,))
    unique_visitors = cursor.fetchone()[0] or 0

    # ── conversion rate via POS 5-min window correlation ─────────────────────
    cursor.execute("""
        SELECT COUNT(DISTINCT e.visitor_id)
        FROM events e
        JOIN pos_transactions p
          ON p.store_id = e.store_id
         AND e.timestamp >= datetime(p.timestamp, '-5 minutes')
         AND e.timestamp <= p.timestamp
        WHERE e.store_id = ?
          AND e.zone_id  = 'BILLING_ZONE'
          AND e.is_staff = 0
    """, (store_id,))
    converted = cursor.fetchone()[0] or 0

    conversion_rate = round(converted / unique_visitors, 4) if unique_visitors > 0 else 0.0

    # ── avg dwell per zone ────────────────────────────────────────────────────
    cursor.execute("""
        SELECT zone_id, AVG(dwell_ms), COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id   = ?
          AND event_type = 'ZONE_DWELL'
          AND is_staff   = 0
          AND zone_id    IS NOT NULL
        GROUP BY zone_id
    """, (store_id,))
    zone_rows = cursor.fetchall()

    avg_dwell_per_zone = {
        row[0]: {
            "avg_dwell_ms":     round(row[1], 0),
            "visitor_count":    row[2],
        }
        for row in zone_rows
    }

    # ── current queue depth (billing zone) ───────────────────────────────────
    cursor.execute("""
        SELECT MAX(CAST(json_extract(metadata, '$.queue_depth') AS INTEGER))
        FROM events
        WHERE store_id   = ?
          AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp  >= datetime('now', '-10 minutes')
    """, (store_id,))
    row = cursor.fetchone()
    queue_depth = row[0] if row and row[0] is not None else 0

    # ── abandonment rate ──────────────────────────────────────────────────────
    # Visitors who reached billing zone but never converted
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id   = ?
          AND zone_id    = 'BILLING_ZONE'
          AND is_staff   = 0
    """, (store_id,))
    reached_billing = cursor.fetchone()[0] or 0

    abandonment_rate = 0.0
    if reached_billing > 0:
        abandonment_rate = round(1 - (converted / reached_billing), 4)

    # ── total revenue from POS ────────────────────────────────────────────────
    cursor.execute("""
        SELECT COUNT(*), IFNULL(SUM(basket_value_inr), 0), IFNULL(AVG(basket_value_inr), 0)
        FROM pos_transactions
        WHERE store_id = ?
    """, (store_id,))
    pos_row = cursor.fetchone()
    transaction_count    = pos_row[0] or 0
    total_revenue        = round(pos_row[1] or 0, 2)
    avg_basket_value     = round(pos_row[2] or 0, 2)

    conn.close()

    return {
        "store_id":           store_id,
        "unique_visitors":    unique_visitors,
        "converted_visitors": converted,
        "conversion_rate":    conversion_rate,
        "queue_depth":        queue_depth,
        "abandonment_rate":   abandonment_rate,
        "reached_billing":    reached_billing,
        "avg_dwell_per_zone": avg_dwell_per_zone,
        "pos": {
            "transaction_count": transaction_count,
            "total_revenue_inr": total_revenue,
            "avg_basket_value":  avg_basket_value,
        },
    }
