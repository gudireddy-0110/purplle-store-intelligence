# PROMPT:
# "Write pytest tests for a FastAPI POST /events/ingest endpoint that accepts
#  batches of up to 500 events and is idempotent by event_id.
#  Cover: single event, batch, duplicate idempotency, batch size limit,
#  partial failure on malformed event, and re-entry funnel deduplication."
#
# CHANGES MADE:
# - AI used requests library directly — replaced with FastAPI TestClient
# - AI's idempotency test only checked status code — added assertion on
#   'duplicate' count in response body
# - Added test_reentry_not_double_counted which AI missed entirely
# - Removed AI's test for async behaviour (not applicable to sync SQLite)

import pytest
import uuid
from fastapi.testclient import TestClient
from app.main     import app
from app.database import init_db, get_connection

STORE  = "STORE_INGEST_TEST"
client = TestClient(app)


def make_event(visitor_id="VIS_001", event_type="ENTRY", store_id=None):
    return {
        "event_id":   str(uuid.uuid4()),
        "store_id":   store_id or STORE,
        "camera_id":  "CAM_ENTRY_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  "2026-03-03T14:22:10Z",
        "zone_id":    None,
        "dwell_ms":   0,
        "is_staff":   False,
        "confidence": 0.91,
        "metadata":   {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM events WHERE store_id = ?", (STORE,))
    conn.commit()
    conn.close()
    yield


class TestIngestEndpoint:

    def test_ingest_single_event(self):
        resp = client.post("/events/ingest", json=[make_event()])
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 1

    def test_ingest_batch(self):
        events = [make_event(visitor_id=f"VIS_{i:03d}") for i in range(50)]
        resp = client.post("/events/ingest", json=events)
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 50

    def test_idempotency_duplicate_ignored(self):
        """Same event_id sent twice — second must be counted as duplicate."""
        event = make_event()

        r1 = client.post("/events/ingest", json=[event])
        assert r1.json()["accepted"]  == 1
        assert r1.json()["duplicate"] == 0

        r2 = client.post("/events/ingest", json=[event])
        assert r2.json()["accepted"]  == 0
        assert r2.json()["duplicate"] == 1

    def test_idempotency_same_payload_twice_safe(self):
        """Full batch sent twice — total DB rows must equal single batch."""
        events = [make_event(visitor_id=f"VIS_{i:03d}") for i in range(10)]
        client.post("/events/ingest", json=events)
        client.post("/events/ingest", json=events)

        conn = get_connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE store_id = ?", (STORE,)
        ).fetchone()[0]
        conn.close()
        assert count == 10   # not 20

    def test_batch_size_limit_exceeded(self):
        """Batch of 501 must be rejected with 400."""
        events = [make_event(visitor_id=f"VIS_{i:04d}") for i in range(501)]
        resp = client.post("/events/ingest", json=events)
        assert resp.status_code == 400

    def test_reentry_not_double_counted_in_visitors(self):
        """
        Same visitor_id with ENTRY + REENTRY must count as 1 unique visitor,
        not 2. Re-entry must not inflate unique_visitors in /metrics.
        """
        entry   = make_event("VIS_reentry", "ENTRY")
        exit_e  = make_event("VIS_reentry", "EXIT")
        reentry = make_event("VIS_reentry", "REENTRY")

        client.post("/events/ingest", json=[entry, exit_e, reentry])

        resp = client.get(f"/stores/{STORE}/metrics")
        assert resp.json()["unique_visitors"] == 1
