from fastapi import FastAPI, HTTPException
from app.metrics import get_store_metrics
from app.models import Event
from app.database import init_db, get_connection

app = FastAPI(title="Purplle Store Intelligence API")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def root():
    return {"message": "API Running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/events/ingest")
def ingest(event: Event):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
        INSERT INTO events (
            event_id, store_id, camera_id, visitor_id, event_type,
            timestamp, zone_id, dwell_ms, is_staff, confidence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.event_id,
            event.store_id,
            event.camera_id,
            event.visitor_id,
            event.event_type,
            event.timestamp,
            event.zone_id,
            event.dwell_ms,
            event.is_staff,
            event.confidence
        ))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    finally:
        conn.close()

    return {"status": "success", "event_id": event.event_id}

@app.get("/events")
def get_events():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM events")
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]
@app.get("/stores/{store_id}/metrics")
def metrics(store_id: str):
    return get_store_metrics(store_id)