"""
Anomaly detection — scans current store state and returns active anomalies.

Detected anomaly types:
  BILLING_QUEUE_SPIKE   — queue depth above threshold
  CONVERSION_DROP       — conversion rate well below 7-day average
  DEAD_ZONE             — no visits to a zone in last 30 minutes
  STALE_FEED            — no events received in last 10 minutes (also in /health)

Severity levels: INFO | WARN | CRITICAL
"""

from datetime import datetime, timezone, timedelta
from app.database import get_connection


# ── thresholds ────────────────────────────────────────────────────────────────
QUEUE_SPIKE_WARN      = 4    # people in billing zone
QUEUE_SPIKE_CRITICAL  = 8
CONVERSION_DROP_WARN  = 0.20  # 20% below 7-day average
CONVERSION_DROP_CRIT  = 0.40  # 40% below
DEAD_ZONE_MINUTES     = 30
STALE_FEED_MINUTES    = 10

TRACKED_ZONES = [
    "SKINCARE_ZONE",
    "MAKEUP_ZONE",
    "FRAGRANCE_ZONE",
    "FACE_SHOP_ZONE",
    "BILLING_ZONE",
]


def get_anomalies(store_id: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    anomalies = []
    now = datetime.now(timezone.utc)

    # ── 1. BILLING_QUEUE_SPIKE ────────────────────────────────────────────────
    cursor.execute("""
        SELECT MAX(CAST(json_extract(metadata, '$.queue_depth') AS INTEGER))
        FROM events
        WHERE store_id   = ?
          AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp  >= datetime('now', '-10 minutes')
    """, (store_id,))
    row = cursor.fetchone()
    current_queue = row[0] if row and row[0] is not None else 0

    if current_queue >= QUEUE_SPIKE_CRITICAL:
        anomalies.append({
            "type":             "BILLING_QUEUE_SPIKE",
            "severity":         "CRITICAL",
            "message":          f"Billing queue depth is {current_queue} — immediate action needed",
            "suggested_action": "Open additional billing counters or redirect staff to checkout",
            "value":            current_queue,
            "threshold":        QUEUE_SPIKE_CRITICAL,
            "detected_at":      now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    elif current_queue >= QUEUE_SPIKE_WARN:
        anomalies.append({
            "type":             "BILLING_QUEUE_SPIKE",
            "severity":         "WARN",
            "message":          f"Billing queue depth is {current_queue} — monitor closely",
            "suggested_action": "Prepare to open a second billing counter",
            "value":            current_queue,
            "threshold":        QUEUE_SPIKE_WARN,
            "detected_at":      now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    # ── 2. CONVERSION_DROP vs 7-day average ───────────────────────────────────
    # Today's conversion rate
    cursor.execute("""
        SELECT COUNT(DISTINCT e.visitor_id)
        FROM events e
        WHERE e.store_id   = ?
          AND e.event_type = 'ENTRY'
          AND e.is_staff   = 0
          AND date(e.timestamp) = date('now')
    """, (store_id,))
    today_visitors = cursor.fetchone()[0] or 0

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
          AND date(e.timestamp) = date('now')
    """, (store_id,))
    today_converted = cursor.fetchone()[0] or 0

    today_rate = today_converted / today_visitors if today_visitors > 0 else 0.0

    # 7-day average (excluding today)
    cursor.execute("""
        SELECT COUNT(DISTINCT e.visitor_id)
        FROM events e
        WHERE e.store_id   = ?
          AND e.event_type = 'ENTRY'
          AND e.is_staff   = 0
          AND date(e.timestamp) BETWEEN date('now', '-7 days') AND date('now', '-1 day')
    """, (store_id,))
    week_visitors = cursor.fetchone()[0] or 0

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
          AND date(e.timestamp) BETWEEN date('now', '-7 days') AND date('now', '-1 day')
    """, (store_id,))
    week_converted = cursor.fetchone()[0] or 0

    week_rate = week_converted / week_visitors if week_visitors > 0 else None

    if week_rate and week_rate > 0 and today_visitors >= 10:
        drop = (week_rate - today_rate) / week_rate
        if drop >= CONVERSION_DROP_CRIT:
            anomalies.append({
                "type":             "CONVERSION_DROP",
                "severity":         "CRITICAL",
                "message":          f"Conversion rate {today_rate:.1%} is {drop:.0%} below 7-day avg {week_rate:.1%}",
                "suggested_action": "Investigate staffing levels, check for product stockouts, review pricing",
                "value":            round(today_rate, 4),
                "baseline":         round(week_rate, 4),
                "drop_pct":         round(drop * 100, 1),
                "detected_at":      now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        elif drop >= CONVERSION_DROP_WARN:
            anomalies.append({
                "type":             "CONVERSION_DROP",
                "severity":         "WARN",
                "message":          f"Conversion rate {today_rate:.1%} is {drop:.0%} below 7-day avg {week_rate:.1%}",
                "suggested_action": "Review floor activity and ensure staff are engaging customers",
                "value":            round(today_rate, 4),
                "baseline":         round(week_rate, 4),
                "drop_pct":         round(drop * 100, 1),
                "detected_at":      now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    # ── 3. DEAD_ZONE — no visits in last 30 minutes ───────────────────────────
    cutoff = (now - timedelta(minutes=DEAD_ZONE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for zone in TRACKED_ZONES:
        cursor.execute("""
            SELECT MAX(timestamp)
            FROM events
            WHERE store_id = ?
              AND zone_id  = ?
              AND is_staff = 0
        """, (store_id, zone))
        row = cursor.fetchone()
        last_visit = row[0] if row else None

        if last_visit is None or last_visit < cutoff:
            anomalies.append({
                "type":             "DEAD_ZONE",
                "severity":         "INFO",
                "message":          f"No customer visits in {zone} for over {DEAD_ZONE_MINUTES} minutes",
                "suggested_action": f"Check if {zone} display is well stocked and visible. Consider repositioning staff nearby.",
                "zone_id":          zone,
                "last_visit":       last_visit,
                "detected_at":      now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    # ── 4. STALE_FEED — no events at all in last 10 minutes ──────────────────
    stale_cutoff = (now - timedelta(minutes=STALE_FEED_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor.execute("""
        SELECT MAX(timestamp) FROM events WHERE store_id = ?
    """, (store_id,))
    row = cursor.fetchone()
    last_event = row[0] if row else None

    if last_event is None or last_event < stale_cutoff:
        anomalies.append({
            "type":             "STALE_FEED",
            "severity":         "CRITICAL",
            "message":          "No events received in the last 10 minutes",
            "suggested_action": "Check camera connectivity and detection pipeline health",
            "last_event":       last_event,
            "detected_at":      now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    conn.close()

    return {
        "store_id":      store_id,
        "active_count":  len(anomalies),
        "anomalies":     anomalies,
        "checked_at":    now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
