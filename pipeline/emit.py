"""
Event schema builder.
Every event emitted by the detection pipeline goes through here.
Ensures schema compliance and globally unique event_ids.
"""

import json
import uuid
from typing import Optional


def emit_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: str,
    zone_id: Optional[str],
    dwell_ms: int,
    is_staff: bool,
    confidence: float,
    session_seq: int,
    queue_depth: Optional[int] = None,
    sku_zone: Optional[str] = None,
    metadata_extra: Optional[dict] = None,
) -> dict:
    """
    Build and return a schema-compliant event dict.

    All events go through this function — never construct raw dicts elsewhere.
    This is the single source of truth for the event schema.
    """
    event = {
        "event_id":   str(uuid.uuid4()),
        "store_id":   store_id,
        "camera_id":  camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  timestamp,
        "zone_id":    zone_id,
        "dwell_ms":   dwell_ms,
        "is_staff":   is_staff,
        "confidence": round(confidence, 4),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone":    sku_zone or zone_id,
            "session_seq": session_seq,
            **(metadata_extra or {}),
        },
    }
    return event


def load_existing_events(path: str) -> list[dict]:
    """Load previously emitted events from a JSONL file."""
    events = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except FileNotFoundError:
        pass
    return events
