#!/bin/bash
# Run detection pipeline on all clips and feed events into the API.
# Usage: bash pipeline/run.sh

set -e

STORE_ID="${STORE_ID:-STORE_BLR_002}"
API_BASE="${API_BASE:-http://localhost:8000}"
VIDEOS_DIR="${VIDEOS_DIR:-data/videos}"
EVENTS_DIR="data/events"

mkdir -p "$EVENTS_DIR"

echo "==> Starting detection pipeline for store: $STORE_ID"

# Process each video file found in data/videos/
for video in "$VIDEOS_DIR"/*.mp4; do
  [ -f "$video" ] || continue

  filename=$(basename "$video" .mp4)
  output="$EVENTS_DIR/${filename}.jsonl"

  echo "--> Processing: $video"
  python -m pipeline.detect \
    --video   "$video" \
    --store   "$STORE_ID" \
    --camera  "CAM_${filename}" \
    --output  "$output"

  echo "--> Ingesting events from $output into API..."
  python - <<EOF
import json, requests, sys

events = []
with open("$output") as f:
    for line in f:
        line = line.strip()
        if line:
            events.append(json.loads(line))

if not events:
    print("  No events to ingest.")
    sys.exit(0)

# Send in batches of 500
batch_size = 500
for i in range(0, len(events), batch_size):
    batch = events[i:i+batch_size]
    r = requests.post("$API_BASE/events/ingest", json=batch, timeout=30)
    r.raise_for_status()
    print(f"  Ingested batch {i//batch_size + 1}: {len(batch)} events → {r.json()}")

print(f"  Total ingested: {len(events)} events")
EOF

done

echo "==> Pipeline complete. Check $API_BASE/stores/$STORE_ID/metrics"
