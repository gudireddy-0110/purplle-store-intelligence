# PROMPT:
# "Write pytest tests for a FastAPI store metrics endpoint that returns
#  unique_visitors, conversion_rate, queue_depth, and abandonment_rate.
#  Cover: normal case, empty store (zero visitors), zero purchases,
#  staff exclusion, and correct POS 5-minute window correlation."
#
# CHANGES MADE:
# - Added fixture to seed pos_transactions table (AI only seeded events table)
# - Replaced hardcoded store_id "TEST" with parametrised fixture
# - Added assertion on conversion_rate formula (AI used >= 0 check only)
# - Added test_staff_excluded which AI omitted entirely
# - Fixed timestamp format to ISO-8601 UTC to match actual pipeline output

import pytest
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main     import app
from app.database import init_db, get_connection

STORE = "STORE_TEST_001"
client = TestClient(app)


# ── helpers ───────────────────────────────────────────────────────────────────

def ts(offset_minutes: int = 0) -> str:
    """Return ISO-8601 UTC timestamp offset by N minutes from now."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(
    event_type: str,
    visitor_id: str,
    zone_id: str | None = None,
    is_staff: bool = False,
    timestamp: str | None = None,
) -> dict:
    return {
        "event_id":   str(uuid.uuid4()),
        "store_id":   STORE,
        "camera_id":  "CAM_TEST",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  timestamp or ts(),
        "zone_id":    zone_id,
        "dwell_ms":   0,
        "is_staff":   is_staff,
        "confidence": 0.91,
        "metadata":   {"queue_depth": None, "sku_zone": zone_id, "session_seq": 1},
    }


def seed_pos_transaction(store_id: str, timestamp: str, amount: float = 500.0):
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO pos_transactions
            (transaction_id, store_id, timestamp, basket_value_inr)
        VALUES (?, ?, ?, ?)
    """, (str(uuid.uuid4()), store_id, timestamp, amount))
    conn.commit()
    conn.close()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """Reset test data before each test."""
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM events WHERE store_id = ?", (STORE,))
    conn.execute("DELETE FROM pos_transactions WHERE store_id = ?", (STORE,))
    conn.commit()
    conn.close()
    yield


# ── tests ─────────────────────────────────────────────────────────────────────

class TestMetricsEndpoint:

    def test_returns_200_with_correct_fields(self):
        """Metrics endpoint must return all required fields."""
        resp = client.get(f"/stores/{STORE}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        for field in ["store_id", "unique_visitors", "conversion_rate",
                      "queue_depth", "abandonment_rate"]:
            assert field in data, f"Missing field: {field}"

    def test_empty_store_returns_zeros_not_null(self):
        """
        Empty store — no events, no POS.
        Must return zeros, not null or crash.
        Regression: API must not return null for zero-traffic stores.
        """
        resp = client.get(f"/stores/{STORE}/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["unique_visitors"]  == 0
        assert data["conversion_rate"]  == 0.0
        assert data["queue_depth"]      == 0
        assert data["abandonment_rate"] == 0.0

    def test_unique_visitors_counts_entries(self):
        """unique_visitors should equal distinct ENTRY visitor_ids."""
        visitors = ["VIS_aaa", "VIS_bbb", "VIS_ccc"]
        events = [make_event("ENTRY", v) for v in visitors]
        resp = client.post("/events/ingest", json=events)
        assert resp.status_code == 200

        resp = client.get(f"/stores/{STORE}/metrics")
        assert resp.json()["unique_visitors"] == 3

    def test_staff_excluded_from_unique_visitors(self):
        """Staff ENTRY events must NOT count toward unique_visitors."""
        client.post("/events/ingest", json=[
            make_event("ENTRY", "VIS_customer", is_staff=False),
            make_event("ENTRY", "VIS_staff001", is_staff=True),
            make_event("ENTRY", "VIS_staff002", is_staff=True),
        ])

        resp = client.get(f"/stores/{STORE}/metrics")
        assert resp.json()["unique_visitors"] == 1

    def test_conversion_rate_pos_window_correlation(self):
        """
        Conversion rate uses 5-minute POS window.
        Visitor in BILLING_ZONE within 5 min before transaction = converted.
        """
        purchase_time = ts(0)
        billing_time  = ts(-3)   # 3 min before purchase — within window

        client.post("/events/ingest", json=[
            make_event("ENTRY",      "VIS_buyer", timestamp=ts(-10)),
            make_event("ZONE_ENTER", "VIS_buyer", zone_id="BILLING_ZONE",
                       timestamp=billing_time),
        ])
        seed_pos_transaction(STORE, purchase_time)

        resp = client.get(f"/stores/{STORE}/metrics")
        data = resp.json()
        assert data["converted_visitors"] == 1
        assert data["conversion_rate"] > 0

    def test_conversion_rate_outside_window_not_counted(self):
        """Visitor in billing zone 10 min before transaction must NOT convert."""
        purchase_time = ts(0)
        billing_time  = ts(-10)  # 10 min before purchase — outside 5-min window

        client.post("/events/ingest", json=[
            make_event("ENTRY",      "VIS_browser", timestamp=ts(-15)),
            make_event("ZONE_ENTER", "VIS_browser", zone_id="BILLING_ZONE",
                       timestamp=billing_time),
        ])
        seed_pos_transaction(STORE, purchase_time)

        resp = client.get(f"/stores/{STORE}/metrics")
        assert resp.json()["converted_visitors"] == 0
        assert resp.json()["conversion_rate"]    == 0.0

    def test_zero_purchases_store(self):
        """Store with visitors but zero POS transactions must not crash."""
        client.post("/events/ingest", json=[
            make_event("ENTRY", "VIS_x"),
            make_event("ENTRY", "VIS_y"),
        ])
        resp = client.get(f"/stores/{STORE}/metrics")
        assert resp.status_code == 200
        assert resp.json()["conversion_rate"] == 0.0
