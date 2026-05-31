from pydantic import BaseModel
from typing import Optional, Any


class EventMetadata(BaseModel):
    queue_depth:  Optional[int]   = None
    sku_zone:     Optional[str]   = None
    session_seq:  Optional[int]   = None


class Event(BaseModel):
    event_id:   str
    store_id:   str
    camera_id:  str
    visitor_id: str
    event_type: str
    timestamp:  str
    zone_id:    Optional[str]           = None
    dwell_ms:   int                     = 0
    is_staff:   bool                    = False
    confidence: float                   = 0.0
    metadata:   Optional[EventMetadata] = None
