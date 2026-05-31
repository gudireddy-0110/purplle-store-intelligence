# PROMPT:
# "Write pytest tests for an anomaly detection module that checks for:
#  BILLING_QUEUE_SPIKE (queue depth > threshold), CONVERSION_DROP vs 7-day avg,
#  DEAD_ZONE (no zone visits in 30 min), and STALE_FEED (no events in 10 min).
#  Each anomaly has a severity: INFO, WARN, or CRITICAL."
#
# CHANGES MADE:
# - AI generated tests that mocked the database — replaced with real DB inserts
#   to actually test the SQL queries, not just the function wrappers
# - Added test for STALE_FEED which AI completely missed
# - Fixed AI's DEAD_ZONE test: it used future timestamps which never trigger the anomaly
# - Separated WARN vs CRITICAL threshold tests (AI merged them into one)
# - Added assertion that anomaly response always has 'suggested_action' field

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main      import app
from app.database  import init_db, get_connection

STORE  = "STORE_ANOMALY_TEST"
client = TestClient(app)


# ── helpers ───────────────────────────────────────────────────────────────────

def ts(offset_minutes: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_event(event_type: str, visitor_id: str, zone_id=None,
                 timestamp=None, is_staff=False, queue_depth=None):
    conn = get_connection()
    metadata = f'{{"queue_depth": {queue_depth}, "sku_zone": null, "session_seq": 1}}' \
               if queue_depth is not None else '{"queue_depth": null}'
    conn.execute("""
        INSERT OR IGNORE INTO events
            (event_id, store_id, camera_id, visitor_id, event_type,
             timestamp, zone_id, dwell_ms, is_staff, confidence, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0.9, ?)
    """, (str(uuid.uuid4()), STORE, "CAM_TEST", visitor_id, event_type,
          timestamp or ts(), zone_id, is_staff, metadata))
    conn.commit()
    conn.close()


def insert_pos(timestamp=None, amount=500.0):
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO pos_transactions
            (transaction_id, store_id, timestamp, basket_value_inr)
        VALUES (?, ?, ?, ?)
    """, (str(uuid.uuid4()), STORE, timestamp or ts(), amount))
    conn.commit()
    conn.close()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM events WHERE store_id = ?", (STORE,))
    conn.execute("DELETE FROM pos_transactions WHERE store_id = ?", (STORE,))
    conn.commit()
    conn.close()
    yield


# ── tests ─────────────────────────────────────────────────────────────────────

class TestAnomaliesEndpoint:

    def test_no_anomalies_clean_store(self):
        """Active store with recent events and good conversion — no anomalies."""
        # Seed recent activity in all zones
        zones = ["SKINCARE_ZONE", "MAKEUP_ZONE", "FRAGRANCE_ZONE",
                 "FACE_SHOP_ZONE", "BILLING_ZONE"]
        for i, zone in enumerate(zones):
            insert_event("ZONE_ENTER", f"VIS_{i:03d}", zone_id=zone,
                         timestamp=ts(-5))
            insert_event("ZONE_DWELL", f"VIS_{i:03d}", zone_id=zone,
                         timestamp=ts(-3))

        resp = client.get(f"/stores/{STORE}/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        # STALE_FEED should not fire since we just inserted events
        types = [a["type"] for a in data["anomalies"]]
        assert "STALE_FEED" not in types

    def test_billing_queue_spike_warn(self):
        """Queue depth >= 4 should trigger BILLING_QUEUE_SPIKE WARN."""
        for i in range(4):
            insert_event("BILLING_QUEUE_JOIN", f"VIS_{i:03d}",
                         zone_id="BILLING_ZONE",
                         timestamp=ts(-2), queue_depth=4)

        resp = client.get(f"/stores/{STORE}/anomalies")
        anomalies = resp.json()["anomalies"]
        queue_anomalies = [a for a in anomalies if a["type"] == "BILLING_QUEUE_SPIKE"]
        assert len(queue_anomalies) >= 1
        assert queue_anomalies[0]["severity"] in ("WARN", "CRITICAL")
        assert "suggested_action" in queue_anomalies[0]

    def test_billing_queue_spike_critical(self):
        """Queue depth >= 8 should trigger CRITICAL severity."""
        for i in range(8):
            insert_event("BILLING_QUEUE_JOIN", f"VIS_{i:03d}",
                         zone_id="BILLING_ZONE",
                         timestamp=ts(-2), queue_depth=8)

        resp = client.get(f"/stores/{STORE}/anomalies")
        anomalies = resp.json()["anomalies"]
        queue_anomalies = [a for a in anomalies if a["type"] == "BILLING_QUEUE_SPIKE"]
        assert any(a["severity"] == "CRITICAL" for a in queue_anomalies)

    def test_dead_zone_fires_for_stale_zone(self):
        """
        DEAD_ZONE anomaly fires when no visits to a zone in last 30 minutes.
        Uses a timestamp 45 minutes ago — well outside the 30-min window.
        """
        insert_event("ZONE_ENTER", "VIS_old", zone_id="MAKEUP_ZONE",
                     timestamp=ts(-45))

        resp = client.get(f"/stores/{STORE}/anomalies")
        anomalies = resp.json()["anomalies"]
        dead_zones = [a for a in anomalies if a["type"] == "DEAD_ZONE"]
        dead_zone_ids = [a["zone_id"] for a in dead_zones]

        assert "MAKEUP_ZONE" in dead_zone_ids
        assert all(a["severity"] == "INFO" for a in dead_zones)
        assert all("suggested_action" in a for a in dead_zones)

    def test_dead_zone_does_not_fire_for_recent_visit(self):
        """Zone visited 5 minutes ago must NOT trigger DEAD_ZONE."""
        zones = ["SKINCARE_ZONE", "MAKEUP_ZONE", "FRAGRANCE_ZONE",
                 "FACE_SHOP_ZONE", "BILLING_ZONE"]
        for zone in zones:
            insert_event("ZONE_ENTER", "VIS_recent", zone_id=zone,
                         timestamp=ts(-5))

        resp = client.get(f"/stores/{STORE}/anomalies")
        anomalies = resp.json()["anomalies"]
        dead_zones = [a for a in anomalies if a["type"] == "DEAD_ZONE"]
        assert len(dead_zones) == 0

    def test_stale_feed_fires_when_no_recent_events(self):
        """
        STALE_FEED fires when no events in last 10 minutes.
        Clean DB (from fixture) → no events at all → must fire STALE_FEED.
        """
        resp = client.get(f"/stores/{STORE}/anomalies")
        anomalies = resp.json()["anomalies"]
        stale = [a for a in anomalies if a["type"] == "STALE_FEED"]
        assert len(stale) >= 1
        assert stale[0]["severity"] == "CRITICAL"
        assert "suggested_action" in stale[0]

    def test_all_anomalies_have_required_fields(self):
        """Every anomaly in the response must have type, severity, suggested_action."""
        resp = client.get(f"/stores/{STORE}/anomalies")
        assert resp.status_code == 200
        for anomaly in resp.json()["anomalies"]:
            assert "type"             in anomaly
            assert "severity"         in anomaly
            assert "suggested_action" in anomaly
            assert anomaly["severity"] in ("INFO", "WARN", "CRITICAL")
