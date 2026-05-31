"""
FastAPI entrypoint — Purplle Store Intelligence API.

Endpoints:
  POST /events/ingest              — batch ingest, idempotent by event_id
  GET  /stores/{id}/metrics        — unique visitors, conversion, dwell, queue
  GET  /stores/{id}/funnel         — Entry → Zone → Billing → Purchase
  GET  /stores/{id}/heatmap        — zone visit frequency + avg dwell, normalised
  GET  /stores/{id}/anomalies      — active anomalies with severity
  GET  /health                     — service status + stale feed check
"""

import time
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.models   import Event
from app.database import init_db, get_connection
from app.metrics  import get_store_metrics
from app.funnel   import get_funnel
from app.anomalies import get_anomalies
from app.database import init_db, load_pos_csv



# ── structured logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}',
)
logger = logging.getLogger("store_intelligence")

STALE_FEED_MINUTES = 10


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_pos_csv("data/resources/pos_transactions.csv")
    yield


app = FastAPI(title="Purplle Store Intelligence API", lifespan=lifespan)


# ── request logging middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id  = str(uuid.uuid4())[:8]
    store_id  = request.path_params.get("store_id", "-")
    start     = time.perf_counter()

    request.state.trace_id = trace_id
    response = await call_next(request)

    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        '"trace_id":"%s","store_id":"%s","endpoint":"%s","method":"%s",'
        '"status_code":%d,"latency_ms":%s',
        trace_id, store_id, request.url.path,
        request.method, response.status_code, latency_ms,
    )
    return response


# ── graceful degradation ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error('"error":"%s","path":"%s"', str(exc), request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error":   "internal_server_error",
            "message": "An unexpected error occurred. No raw trace exposed.",
            "path":    request.url.path,
        },
    )


# ── root ──────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Purplle Store Intelligence API", "version": "1.0.0"}


# ── health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    conn = get_connection()
    cursor = conn.cursor()

    # Last event timestamp per store
    cursor.execute("""
        SELECT store_id, MAX(timestamp) as last_event
        FROM events
        GROUP BY store_id
    """)
    rows = cursor.fetchall()
    conn.close()

    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(minutes=STALE_FEED_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    store_status = {}
    for row in rows:
        sid       = row["store_id"]
        last_evt  = row["last_event"]
        is_stale  = last_evt is None or last_evt < stale_cutoff
        store_status[sid] = {
            "last_event_timestamp": last_evt,
            "feed_status": "STALE_FEED" if is_stale else "OK",
        }

    return {
        "status":      "healthy",
        "checked_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stores":      store_status,
    }


# ── events ingest (batch, idempotent) ─────────────────────────────────────────
@app.post("/events/ingest")
def ingest(events: List[Event], request: Request):
    """
    Accepts a batch of up to 500 events.
    Idempotent by event_id — duplicate event_ids are silently skipped.
    Returns per-event success/failure breakdown.
    """
    if len(events) > 500:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(events)} exceeds maximum of 500",
        )

    conn   = get_connection()
    cursor = conn.cursor()

    accepted  = 0
    duplicate = 0
    failed    = []

    for evt in events:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO events (
                    event_id, store_id, camera_id, visitor_id, event_type,
                    timestamp, zone_id, dwell_ms, is_staff, confidence, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                evt.event_id,
                evt.store_id,
                evt.camera_id,
                evt.visitor_id,
                evt.event_type,
                evt.timestamp,
                evt.zone_id,
                evt.dwell_ms,
                evt.is_staff,
                evt.confidence,
                str(evt.metadata) if evt.metadata else None,
            ))

            if cursor.rowcount == 1:
                accepted += 1
            else:
                duplicate += 1

        except Exception as e:
            failed.append({"event_id": evt.event_id, "error": str(e)})

    conn.commit()
    conn.close()

    trace_id = getattr(request.state, "trace_id", "-")
    logger.info(
        '"trace_id":"%s","endpoint":"/events/ingest","event_count":%d,'
        '"accepted":%d,"duplicate":%d,"failed":%d',
        trace_id, len(events), accepted, duplicate, len(failed),
    )

    return {
        "status":    "ok" if not failed else "partial",
        "accepted":  accepted,
        "duplicate": duplicate,
        "failed":    failed,
    }


# ── store metrics ─────────────────────────────────────────────────────────────
@app.get("/stores/{store_id}/metrics")
def metrics(store_id: str):
    return get_store_metrics(store_id)


# ── funnel ────────────────────────────────────────────────────────────────────
@app.get("/stores/{store_id}/funnel")
def funnel(store_id: str):
    return get_funnel(store_id)


# ── heatmap ───────────────────────────────────────────────────────────────────
@app.get("/stores/{store_id}/heatmap")
def heatmap(store_id: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT zone_id,
               COUNT(DISTINCT visitor_id) as visit_count,
               AVG(dwell_ms)              as avg_dwell_ms
        FROM events
        WHERE store_id   = ?
          AND event_type = 'ZONE_DWELL'
          AND is_staff   = 0
          AND zone_id    IS NOT NULL
        GROUP BY zone_id
    """, (store_id,))
    rows = cursor.fetchall()

    # Total unique sessions for confidence check
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id   = ?
          AND event_type = 'ENTRY'
          AND is_staff   = 0
    """, (store_id,))
    total_sessions = cursor.fetchone()[0] or 0
    conn.close()

    if not rows:
        return {
            "store_id":        store_id,
            "data_confidence": "LOW",
            "heatmap":         [],
        }

    # Normalise visit_count 0–100 across zones
    max_visits   = max(r["visit_count"] for r in rows) or 1
    max_dwell    = max(r["avg_dwell_ms"] for r in rows) or 1

    heatmap_data = [
        {
            "zone_id":          row["zone_id"],
            "visit_count":      row["visit_count"],
            "avg_dwell_ms":     round(row["avg_dwell_ms"] or 0, 0),
            "visit_score":      round(row["visit_count"] / max_visits * 100, 1),
            "dwell_score":      round((row["avg_dwell_ms"] or 0) / max_dwell * 100, 1),
        }
        for row in rows
    ]

    return {
        "store_id":        store_id,
        "data_confidence": "LOW" if total_sessions < 20 else "HIGH",
        "total_sessions":  total_sessions,
        "heatmap":         sorted(heatmap_data, key=lambda x: x["visit_score"], reverse=True),
    }


# ── anomalies ─────────────────────────────────────────────────────────────────
@app.get("/stores/{store_id}/anomalies")
def anomalies(store_id: str):
    return get_anomalies(store_id)
