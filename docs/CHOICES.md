# CHOICES.md — Engineering Decisions

Three decisions that shaped this system, with full reasoning on what I
considered, what AI suggested, and what I ultimately chose and why.

---

## Decision 1: Detection Model — YOLOv8n + YOLO built-in tracking

### What I needed
A model that could:
- Run on a single machine without a GPU farm
- Track the same person across frames (not just detect frame-by-frame)
- Handle partial occlusion without silent failures
- Process 20-minute clips in a reasonable time window

### Options I considered

| Option | Pros | Cons |
|---|---|---|
| YOLOv8n (chosen) | Lightweight, fast, built-in `.track()` mode, huge community | Less accurate than larger models on occlusion |
| YOLOv8x | Better accuracy, handles occlusion better | 5-6x slower — unusable on standard hardware for 20-min clips |
| RT-DETR | State-of-the-art accuracy, transformer-based | No native tracking mode, would need separate ByteTrack integration, higher complexity |
| Faster R-CNN | Good accuracy | Too slow for real-time or near-real-time use, 2-3 FPS vs YOLO's 30+ |
| MediaPipe | Fast, lightweight | Not designed for multi-person tracking, loses IDs easily in crowds |

### What AI suggested
When I asked Claude to compare detection models for retail CCTV analytics,
it recommended YOLOv8 + ByteTrack as the industry standard combo. It noted
that RT-DETR would give better accuracy on partial occlusion but warned that
integrating a separate tracker would add significant complexity and failure
points for a single-developer build.

### What I chose and why
I agreed with the YOLOv8 recommendation but chose the built-in `.track()`
mode (which uses BoT-SORT under the hood) over adding ByteTrack separately.
The reasoning: the built-in tracker gives stable `track_id` persistence across
frames with zero integration overhead. ByteTrack would give marginally better
re-identification on long occlusions, but the practical difference on 20-minute
retail clips is small compared to the added complexity.

The key trade-off I accepted: YOLOv8n will occasionally lose a track_id during
long occlusion (someone behind a display shelf). I handle this with a timeout-based
synthetic EXIT in `tracker.py` rather than pretending the detection was perfect.
Confidence is always emitted, never suppressed — reviewers can see where the
system is uncertain.

---

## Decision 2: Event Schema Design

### What I needed
A schema that could:
- Support all analytics queries (funnel, heatmap, anomaly detection)
- Carry enough context per event to be useful without re-querying
- Be idempotent by `event_id` for safe re-ingestion
- Work for both real-time streaming and batch replay

### The core tension
Flat schema vs nested metadata. A fully flat schema is simple to query in SQL
but forces nullable columns for every event type. A nested `metadata` blob is
flexible but makes querying harder.

### What AI suggested
When I shared the problem schema requirements, AI suggested a hybrid: core
fields flat (the ones every event has), optional fields in a JSON `metadata`
column. It specifically flagged that `queue_depth` and `session_seq` are
event-type-specific and would pollute the flat schema with mostly-null columns.

### What I chose and why
I agreed with the hybrid approach. Core fields (`event_id`, `store_id`,
`camera_id`, `visitor_id`, `event_type`, `timestamp`, `zone_id`, `dwell_ms`,
`is_staff`, `confidence`) are flat columns — indexed and queryable directly.
Event-specific fields (`queue_depth`, `sku_zone`, `session_seq`) live in the
`metadata` JSON column.

One place I **overrode** AI's suggestion: it recommended storing `metadata`
as a separate joined table for query performance. I rejected this because the
challenge scope is a single store prototype — the join overhead would add
complexity with no measurable benefit at this scale. I documented this in
DESIGN.md as a known trade-off.

The other key schema decision: I emit low-confidence events with the confidence
score visible rather than filtering them out. The challenge spec explicitly
requires this, and it lets the API consumer decide their own confidence
threshold rather than baking it into the pipeline.

---

## Decision 3: API Architecture — FastAPI + SQLite, single-container

### What I needed
An API that:
- Starts with `docker compose up`, zero manual steps
- Handles idempotent batch ingestion
- Returns real-time metrics (not yesterday's cache)
- Is observable enough for an on-call engineer

### Options I considered

| Option | Pros | Cons |
|---|---|---|
| FastAPI + SQLite (chosen) | Zero infra setup, fast dev, Pydantic validation, WAL mode handles concurrent reads | Not horizontally scalable, single-writer limit |
| FastAPI + PostgreSQL | Production-grade, concurrent writes, better for multi-store scale | Requires a separate container, connection pooling, more setup complexity |
| Flask + SQLite | Familiar, simple | No async support, manual validation, slower |
| FastAPI + Redis | Great for real-time queue metrics | Volatile storage, would need a persistence layer too |

### What AI suggested
AI strongly recommended PostgreSQL over SQLite for "production readiness."
It argued that a real 40-store deployment would need concurrent writes from
multiple pipeline instances.

### What I chose and why
I disagreed and chose SQLite with WAL mode for this submission. My reasoning:

1. The challenge explicitly says "SQLite is fine" in the FAQ
2. `docker compose up` with SQLite needs one container; PostgreSQL needs two
   plus connection management — meaningfully more setup failure surface
3. WAL mode in SQLite handles concurrent readers + one writer, which is exactly
   the pattern here: one pipeline writing, multiple API readers
4. I documented this in DESIGN.md as a scale limitation: if this were deployed
   across 40 live stores with parallel pipelines, I would migrate to PostgreSQL
   and add a message queue (Kafka or Redis Streams) between the detection layer
   and the ingest API

The honest trade-off: I optimised for correctness and zero-friction setup over
theoretical scale. At the challenge scope, SQLite is the right tool.

---

## Summary of Trade-offs

| Decision | What I optimised for | What I gave up |
|---|---|---|
| YOLOv8n + built-in tracker | Low complexity, fast iteration | Marginal accuracy on long occlusions |
| Hybrid event schema | Query simplicity on core fields | Metadata needs json_extract() in some queries |
| SQLite + WAL | Zero-friction deployment | Horizontal write scalability |

All three trade-offs are reasonable for a prototype that needs to ship in 48
hours and be operated by a reviewer who just ran `docker compose up`.
