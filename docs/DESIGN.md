# DESIGN.md — System Architecture

## System Goal

Build a store intelligence platform that processes raw CCTV footage and
produces real-time business metrics — specifically offline store conversion rate.

Every component exists to improve either the **accuracy** of that metric
(detection layer) or its **actionability** (API layer).

---

## Architecture Overview

```
CCTV Video Clips
      │
      ▼
pipeline/detect.py          ← YOLOv8n + BoT-SORT tracking
      │  Per-frame detection, entry/exit line crossing, zone mapping
      │  Emits structured JSON events to JSONL file
      ▼
pipeline/emit.py             ← Single schema source of truth
      │  UUID event_id, ISO-8601 timestamps, confidence always included
      ▼
POST /events/ingest          ← Batch (500), idempotent by event_id
      │
      ▼
SQLite (WAL mode)            ← events + pos_transactions tables
      │
      ├── GET /stores/{id}/metrics    ← visitors, conversion, dwell, queue
      ├── GET /stores/{id}/funnel     ← 4-stage session funnel
      ├── GET /stores/{id}/heatmap    ← zone frequency, normalised 0-100
      ├── GET /stores/{id}/anomalies  ← QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE
      └── GET /health                 ← STALE_FEED detection per store
              │
              ▼
      Streamlit Dashboard     ← live auto-refresh every 2 seconds
```

---

## Component Decisions

### Detection Layer (`pipeline/`)

**Entry/exit detection** uses a horizontal line at 55% of frame height.
A person whose bounding box center crosses this line downward = ENTRY,
upward = EXIT. This is a deliberate simplification — optical flow or
homography-based approaches are more accurate but add significant complexity
for marginal gain on a fixed-angle entry camera.

**Re-entry detection**: each `track_id` from YOLO is mapped to a stable
`visitor_id`. The tracker remembers whether a `track_id` has previously
exited. If the same `track_id` crosses the entry line after an EXIT event,
it emits `REENTRY` instead of `ENTRY`. This prevents visit count inflation.

**Staff detection**: positional heuristic — persons whose bounding box center
appears in the top 10% of the frame (behind-counter area) are flagged
`is_staff=True`. This is imperfect but practical without a uniform classifier.
All `is_staff=True` events are excluded from customer metrics.

**Lost track handling**: if a `track_id` disappears without crossing the exit
line (walked off-camera, occluded), a synthetic EXIT is emitted. Confidence
is set to 0.0 to signal that this is a model assumption, not a detection.

### Event Schema (`pipeline/emit.py`)

All events flow through a single `emit_event()` function — no raw dict
construction elsewhere. This guarantees schema compliance and unique `event_id`
values across the entire pipeline run.

Low-confidence detections are always emitted (never silently dropped).
The `confidence` field lets the API consumer apply their own threshold.

### API Layer (`app/`)

**Idempotency**: `POST /events/ingest` uses `INSERT OR IGNORE` keyed on
`event_id`. Safe to call twice with the same payload — duplicates are counted
and reported but do not cause errors or data corruption.

**POS correlation**: conversion is computed by joining events to
`pos_transactions` on a 5-minute time window. A visitor who was in
`BILLING_ZONE` within 5 minutes before a transaction timestamp is counted
as converted. This is an approximation — there is no `customer_id` in the
POS data — but it is the correct approach given the data available.

**Real-time metrics**: all `/metrics` queries run live against the database.
No caching layer. This is correct for the challenge scope; at 40-store
production scale I would add a Redis cache with a 30-second TTL.

### Storage (`app/database.py`)

SQLite with WAL (Write-Ahead Logging) mode. WAL allows concurrent reads while
a write is in progress, which matches the access pattern: one pipeline writer,
multiple API readers.

Three indexes:
- `(store_id, timestamp)` — all time-window queries
- `(visitor_id)` — funnel deduplication
- `(store_id, zone_id, timestamp)` — zone analytics and dead zone detection

Known limitation: single-writer. At 40 live stores with parallel pipelines,
this would become a bottleneck. Migration path: PostgreSQL + connection pool,
or a message queue (Kafka/Redis Streams) in front of the ingest endpoint.

---

## AI-Assisted Decisions

### 1. Hybrid event schema (flat core + JSON metadata)

I was initially planning a fully flat schema with nullable columns for every
event-type-specific field. When I described the schema requirements to Claude,
it flagged that `queue_depth` and `session_seq` are event-type-specific and
would create a sparse table with many nulls — a sign of a schema design smell.

It suggested a hybrid: flat columns for universal fields, a JSON `metadata`
column for event-specific fields. I agreed and implemented this. The trade-off
is that some queries need `json_extract(metadata, '$.queue_depth')`, which is
slightly awkward in SQLite. I decided that was acceptable given the
significantly cleaner schema.

**Verdict: agreed with AI suggestion and implemented it.**

### 2. ByteTrack vs built-in YOLO tracker

When I asked Claude to compare tracking algorithms for this use case, it
recommended YOLOv8 + ByteTrack as the "standard production pairing," arguing
that ByteTrack handles occlusion better than BoT-SORT.

I overrode this. YOLO's built-in `.track()` mode uses BoT-SORT and requires
zero additional integration — no extra library, no separate process, no schema
mapping between ByteTrack output and my event format. For a 48-hour build,
that complexity reduction matters more than marginal tracking accuracy on
occlusion edge cases. The difference would matter in a production system with
a dedicated ML engineer; it does not matter here.

**Verdict: overrode AI suggestion. Chose simplicity over marginal accuracy gain.**

### 3. Anomaly thresholds

When building `anomalies.py`, I asked Claude what reasonable thresholds would
be for a retail store: queue spike, conversion drop, dead zone timeout.

It suggested a queue spike threshold of 3 people (WARN) and 6 (CRITICAL),
and a 15-minute dead zone window. I adjusted these upward: 4/8 for queue
(a 3-person queue in a beauty retail store is normal at peak hours), and
30 minutes for dead zone (short windows produce noisy alerts during natural
footfall lulls like mid-morning).

**Verdict: used AI suggestion as a starting point, adjusted based on retail
domain reasoning.**

---

## Known Limitations and Future Work

| Limitation | Impact | Migration Path |
|---|---|---|
| Staff detection is positional, not visual | May misclassify staff who move to floor | Train a uniform classifier with store footage |
| Single-camera entry line | Cross-camera deduplication not implemented | Add Re-ID embedding comparison across camera feeds |
| SQLite single-writer | Bottleneck at 40 live stores | PostgreSQL + connection pool |
| No message queue | Pipeline must push directly to API | Add Kafka/Redis Streams between pipeline and ingest |
| Zone boundaries are manually defined | Zones are approximate | Use store_layout.json polygon coordinates for exact boundaries |
