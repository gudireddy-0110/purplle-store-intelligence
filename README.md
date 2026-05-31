# Purplle Store Intelligence System

End-to-end store analytics pipeline — from raw CCTV footage to a live intelligence API and dashboard.

---

## Quick Start (5 commands)

```bash
# 1. Clone the repo
git clone https://github.com/gudireddy-0110/purplle-store-intelligence.git
cd purplle-store-intelligence

# 2. Add your video clips and POS data
cp /path/to/your/clips/*.mp4 data/videos/
cp /path/to/pos_transactions.csv data/resources/

# 3. Start the API and dashboard
docker compose up --build

# 4. Run the detection pipeline against the clips
bash pipeline/run.sh

# 5. Open the live dashboard
# http://localhost:8501
```

API is available at `http://localhost:8000` · Swagger docs at `http://localhost:8000/docs`

---

## What This System Does

A specialty retail chain has no visibility into offline store behaviour. This system bridges that gap — starting from raw CCTV footage and ending with a live analytics API that answers:

| Business Question | Answered By |
|---|---|
| How many customers visited today and how many bought? | `GET /stores/{id}/metrics` → `conversion_rate` |
| Where in the store are we losing customers? | `GET /stores/{id}/funnel` → drop-off % per stage |
| Which zones get attention but no sales? | `GET /stores/{id}/heatmap` → dwell vs billing reach |
| Is there a queue building right now? | `GET /stores/{id}/anomalies` → `BILLING_QUEUE_SPIKE` |
| Is any camera feed stale? | `GET /health` → `STALE_FEED` warning |

---

## Architecture

```
CCTV Videos (.mp4)
      ↓
pipeline/detect.py        YOLOv8n detection + model.track() per-frame
      ↓
pipeline/tracker.py       visitor_id assignment, re-entry detection, zone state
      ↓
pipeline/emit.py          schema-compliant event builder (UUID event_ids)
      ↓
data/events/*.jsonl       structured event stream written to disk
      ↓
pipeline/run.sh           batch POST → /events/ingest
      ↓
FastAPI (port 8000)       ingest, deduplicate, store in SQLite
      ↓
app/metrics.py            unique visitors, conversion rate, dwell, queue depth
app/funnel.py             4-stage session funnel with drop-off %
app/anomalies.py          BILLING_QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE
      ↓
Streamlit (port 8501)     live dashboard — auto-refreshes every 3 seconds
```

---

## Running the Detection Pipeline

Place your `.mp4` files in `data/videos/` before running.

```bash
# Process all clips in data/videos/ and ingest events into the API
bash pipeline/run.sh

# Or process a single clip manually
python -m pipeline.detect \
  --video   data/videos/CAM_ENTRY.mp4 \
  --store   STORE_BLR_002 \
  --camera  CAM_ENTRY_01 \
  --output  data/events/events.jsonl
```

Events are written to `data/events/*.jsonl` and then batch-ingested into the API via `POST /events/ingest`.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service status + stale feed check per store |
| `POST` | `/events/ingest` | Batch ingest up to 500 events (idempotent by `event_id`) |
| `GET` | `/stores/{id}/metrics` | Unique visitors, conversion rate, queue depth, abandonment rate |
| `GET` | `/stores/{id}/funnel` | Entry → Zone → Billing → Purchase with drop-off % |
| `GET` | `/stores/{id}/heatmap` | Zone visit frequency + avg dwell, normalised 0–100 |
| `GET` | `/stores/{id}/anomalies` | Active anomalies with severity (INFO / WARN / CRITICAL) |

Full interactive docs: `http://localhost:8000/docs`

---

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

Test files cover: empty store, zero purchases, staff exclusion, re-entry deduplication, queue spike thresholds, dead zone detection, and all required response fields.

---

## Project Structure

```
purplle-store-intelligence/
├── pipeline/
│   ├── detect.py       Main detection + tracking script
│   ├── tracker.py      visitor_id assignment, re-entry detection
│   ├── emit.py         Event schema builder
│   └── run.sh          One command: process all clips → ingest to API
├── app/
│   ├── main.py         FastAPI entrypoint + all endpoints
│   ├── models.py       Pydantic event schema
│   ├── database.py     SQLite setup + POS CSV loader
│   ├── metrics.py      Real-time metric computation
│   ├── funnel.py       Session-based funnel logic
│   ├── anomalies.py    Anomaly detection rules
│   └── health.py
├── dashboard/
│   └── dashboard.py    Streamlit live dashboard (auto-refresh)
├── tests/
│   ├── test_metrics.py
│   └── test_anomalies.py
├── docs/
│   ├── DESIGN.md       Architecture + AI-Assisted Decisions
│   └── CHOICES.md      3 engineering decisions with full reasoning
├── data/
│   ├── videos/         Place .mp4 clips here (not committed)
│   ├── resources/      pos_transactions.csv goes here
│   └── events/         Pipeline output — JSONL event files
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Detection | YOLOv8n (Ultralytics), OpenCV |
| Tracking | YOLO built-in ByteTrack (`model.track()`) |
| Backend | FastAPI, SQLite (WAL mode) |
| Analytics | Pandas, NumPy |
| Dashboard | Streamlit |
| Containerisation | Docker, docker compose |

---

## Key Design Decisions

Full reasoning in `docs/CHOICES.md` and `docs/DESIGN.md`.

- **YOLOv8n over RT-DETR** — faster on CPU, well-calibrated confidence scores, zero extra tracking infrastructure via `model.track()`
- **Single event schema** — one table, one JSONL format, one schema builder function — simpler than Kafka topics per event type for this scale
- **SQLite with WAL mode** — zero-friction docker deployment; PostgreSQL upgrade path documented in CHOICES.md

---

## Assumptions

- Entry/exit threshold is a horizontal line at 55% of frame height
- Persons detected in the top 10% of the entry camera frame are classified as staff
- Zones are mapped by frame coordinate ratios (no exact pixel coordinates from layout)
- POS correlation uses a 5-minute window before transaction timestamp
- Each YOLO `track_id` maps to one `visitor_id` per session

---

## Future Improvements

- Cross-camera Re-ID (OSNet / torchreid) to deduplicate visitors across the entry and floor cameras
- PostgreSQL for production-scale concurrent writes from 40 stores
- Kafka for real-time event streaming instead of batch file ingestion
- VLM-based staff detection by uniform colour once face-blur issues are resolved
