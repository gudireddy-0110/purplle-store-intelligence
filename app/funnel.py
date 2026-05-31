"""
Funnel logic — Entry → Zone Visit → Billing Queue → Purchase.

Rules:
- Unit of analysis is a SESSION, not a raw event
- Re-entries must NOT double-count a visitor
- A visitor who re-enters counts as ONE unique visitor in the funnel
- Each stage shows count + drop-off % from previous stage
"""

from app.database import get_connection


def get_funnel(store_id: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    # ── Stage 1: unique visitors who ENTERED (exclude re-entries & staff) ──────
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id = ?
          AND event_type = 'ENTRY'
          AND is_staff   = 0
    """, (store_id,))
    total_entries = cursor.fetchone()[0] or 0

    # ── Stage 2: visitors who entered at least one named zone ─────────────────
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id  = ?
          AND event_type = 'ZONE_ENTER'
          AND is_staff   = 0
          AND visitor_id IN (
              SELECT DISTINCT visitor_id
              FROM events
              WHERE store_id  = ?
                AND event_type = 'ENTRY'
                AND is_staff   = 0
          )
    """, (store_id, store_id))
    zone_visitors = cursor.fetchone()[0] or 0

    # ── Stage 3: visitors who reached billing zone ────────────────────────────
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id  = ?
          AND event_type IN ('BILLING_QUEUE_JOIN', 'ZONE_ENTER')
          AND zone_id    = 'BILLING_ZONE'
          AND is_staff   = 0
          AND visitor_id IN (
              SELECT DISTINCT visitor_id
              FROM events
              WHERE store_id  = ?
                AND event_type = 'ENTRY'
                AND is_staff   = 0
          )
    """, (store_id, store_id))
    billing_visitors = cursor.fetchone()[0] or 0

    # ── Stage 4: visitors who converted (POS 5-min window correlation) ────────
    # A visitor counts as converted if they were in BILLING_ZONE in the
    # 5-minute window before any POS transaction timestamp.
    cursor.execute("""
        SELECT COUNT(DISTINCT e.visitor_id)
        FROM events e
        JOIN pos_transactions p
          ON p.store_id = e.store_id
         AND e.timestamp >= datetime(p.timestamp, '-5 minutes')
         AND e.timestamp <= p.timestamp
        WHERE e.store_id   = ?
          AND e.zone_id    = 'BILLING_ZONE'
          AND e.is_staff   = 0
          AND e.visitor_id IN (
              SELECT DISTINCT visitor_id
              FROM events
              WHERE store_id  = ?
                AND event_type = 'ENTRY'
                AND is_staff   = 0
          )
    """, (store_id, store_id))
    converted_visitors = cursor.fetchone()[0] or 0

    conn.close()

    # ── compute drop-offs ─────────────────────────────────────────────────────
    def drop_off(current: int, previous: int) -> float:
        if previous == 0:
            return 0.0
        return round((1 - current / previous) * 100, 1)

    def conversion_pct(current: int, base: int) -> float:
        if base == 0:
            return 0.0
        return round(current / base * 100, 1)

    return {
        "store_id": store_id,
        "funnel": [
            {
                "stage":          "entry",
                "label":          "Visitors entered store",
                "count":          total_entries,
                "drop_off_pct":   0.0,
                "conversion_pct": 100.0,
            },
            {
                "stage":          "zone_visit",
                "label":          "Visited at least one zone",
                "count":          zone_visitors,
                "drop_off_pct":   drop_off(zone_visitors, total_entries),
                "conversion_pct": conversion_pct(zone_visitors, total_entries),
            },
            {
                "stage":          "billing_queue",
                "label":          "Reached billing zone",
                "count":          billing_visitors,
                "drop_off_pct":   drop_off(billing_visitors, zone_visitors),
                "conversion_pct": conversion_pct(billing_visitors, total_entries),
            },
            {
                "stage":          "purchase",
                "label":          "Completed a purchase",
                "count":          converted_visitors,
                "drop_off_pct":   drop_off(converted_visitors, billing_visitors),
                "conversion_pct": conversion_pct(converted_visitors, total_entries),
            },
        ],
        "summary": {
            "total_visitors":     total_entries,
            "converted_visitors": converted_visitors,
            "overall_conversion_rate_pct": conversion_pct(converted_visitors, total_entries),
        },
    }
