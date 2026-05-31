"""
Main detection script.
Processes CCTV video clips, detects people, tracks movement,
determines entry/exit direction, and emits structured JSON events.

Usage:
    python -m pipeline.detect --video data/videos/CAM_ENTRY.mp4 \
                               --store STORE_BLR_002 \
                               --camera CAM_ENTRY_01 \
                               --output data/events/events.jsonl
"""

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
from ultralytics import YOLO

from pipeline.tracker import VisitorTracker
from pipeline.emit import emit_event, load_existing_events

# ── configuration ──────────────────────────────────────────────────────────────
ENTRY_LINE_RATIO = 0.55          # horizontal line at 55% of frame height
STAFF_ZONE_RATIO = 0.10          # top 10% of frame = staff-only area (behind counter)
CONFIDENCE_THRESHOLD = 0.35      # minimum detection confidence to process
DWELL_EMIT_INTERVAL_SEC = 30     # emit ZONE_DWELL every N seconds of continuous dwell

# Zone definitions — map frame regions to store zone names
# Format: (x_min_ratio, y_min_ratio, x_max_ratio, y_max_ratio) -> zone_name
ZONE_MAP = [
    (0.0,  0.0,  0.33, 0.5,  "SKINCARE_ZONE"),
    (0.33, 0.0,  0.66, 0.5,  "MAKEUP_ZONE"),
    (0.66, 0.0,  1.0,  0.5,  "FRAGRANCE_ZONE"),
    (0.0,  0.5,  0.5,  1.0,  "FACE_SHOP_ZONE"),
    (0.5,  0.5,  1.0,  1.0,  "BILLING_ZONE"),
]


def get_zone(cx_ratio: float, cy_ratio: float) -> str | None:
    """Return zone name for a bounding box center, or None if not in any zone."""
    for x0, y0, x1, y1, name in ZONE_MAP:
        if x0 <= cx_ratio <= x1 and y0 <= cy_ratio <= y1:
            return name
    return None


def is_staff_position(cy_ratio: float) -> bool:
    """Heuristic: person in top strip of frame is likely staff behind counter."""
    return cy_ratio < STAFF_ZONE_RATIO


def crosses_line(prev_cy: float, curr_cy: float, line_y: float) -> str | None:
    """
    Returns 'ENTRY' if center crossed line downward (into store),
    'EXIT' if crossed upward (leaving store), else None.
    """
    if prev_cy < line_y <= curr_cy:
        return "ENTRY"
    if prev_cy >= line_y > curr_cy:
        return "EXIT"
    return None


def process_video(
    video_path: str,
    store_id: str,
    camera_id: str,
    output_path: str,
    clip_start_time: str | None = None,
) -> list[dict]:
    """
    Process a single video clip and return list of emitted events.

    Args:
        video_path:        Path to the CCTV clip.
        store_id:          Store identifier from store_layout.json.
        camera_id:         Camera identifier.
        output_path:       Path to write events JSONL file.
        clip_start_time:   ISO-8601 UTC timestamp for frame 0.
                           Defaults to current UTC time.
    """
    model = YOLO("yolov8n.pt")
    tracker = VisitorTracker()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    entry_line_y = frame_h * ENTRY_LINE_RATIO

    # Timestamp of the first frame
    t0 = datetime.fromisoformat(clip_start_time) if clip_start_time \
        else datetime.now(timezone.utc)

    all_events: list[dict] = []
    frame_idx = 0

    # Zone dwell tracking: {visitor_id: {zone: last_dwell_emit_frame}}
    dwell_state: dict[str, dict[str, int]] = {}

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "a") as out_f:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1
            elapsed_sec = frame_idx / fps
            frame_ts = t0.replace(
                second=0, microsecond=0
            )
            # Build precise timestamp from frame offset
            from datetime import timedelta
            frame_ts = t0 + timedelta(seconds=elapsed_sec)
            ts_str = frame_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

            # ── run YOLO tracking ──────────────────────────────────────────
            results = model.track(
                frame,
                persist=True,
                classes=[0],        # person only
                conf=CONFIDENCE_THRESHOLD,
                verbose=False,
            )

            current_track_ids = set()

            for result in results:
                if result.boxes is None:
                    continue

                for box in result.boxes:
                    if box.id is None:
                        continue

                    track_id = int(box.id[0])
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2
                    cx_r = cx / frame_w
                    cy_r = cy / frame_h

                    is_staff = is_staff_position(cy_r)
                    current_track_ids.add(track_id)

                    # ── get or create visitor session ──────────────────────
                    visitor_id, prev_cy, session_seq, had_exited = \
                        tracker.update(track_id, cy, frame_idx)

                    # ── entry / exit detection ─────────────────────────────
                    if prev_cy is not None:
                        direction = crosses_line(prev_cy, cy, entry_line_y)

                        if direction == "ENTRY":
                            event_type = "REENTRY" if had_exited else "ENTRY"
                            evt = emit_event(
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type=event_type,
                                timestamp=ts_str,
                                zone_id=None,
                                dwell_ms=0,
                                is_staff=is_staff,
                                confidence=conf,
                                session_seq=session_seq,
                            )
                            all_events.append(evt)
                            out_f.write(json.dumps(evt) + "\n")
                            out_f.flush()
                            tracker.mark_entered(track_id)

                        elif direction == "EXIT":
                            evt = emit_event(
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type="EXIT",
                                timestamp=ts_str,
                                zone_id=None,
                                dwell_ms=0,
                                is_staff=is_staff,
                                confidence=conf,
                                session_seq=session_seq,
                            )
                            all_events.append(evt)
                            out_f.write(json.dumps(evt) + "\n")
                            out_f.flush()
                            tracker.mark_exited(track_id)

                    # ── zone detection ─────────────────────────────────────
                    zone = get_zone(cx_r, cy_r)
                    if zone and tracker.is_inside_store(track_id):
                        prev_zone = tracker.get_zone(track_id)

                        if prev_zone != zone:
                            # Zone enter
                            if prev_zone is not None:
                                evt = emit_event(
                                    store_id=store_id,
                                    camera_id=camera_id,
                                    visitor_id=visitor_id,
                                    event_type="ZONE_EXIT",
                                    timestamp=ts_str,
                                    zone_id=prev_zone,
                                    dwell_ms=0,
                                    is_staff=is_staff,
                                    confidence=conf,
                                    session_seq=session_seq,
                                )
                                all_events.append(evt)
                                out_f.write(json.dumps(evt) + "\n")

                            evt = emit_event(
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type="ZONE_ENTER",
                                timestamp=ts_str,
                                zone_id=zone,
                                dwell_ms=0,
                                is_staff=is_staff,
                                confidence=conf,
                                session_seq=session_seq,
                                queue_depth=tracker.get_queue_depth(zone),
                            )
                            all_events.append(evt)
                            out_f.write(json.dumps(evt) + "\n")
                            out_f.flush()
                            tracker.set_zone(track_id, zone, frame_idx)

                        else:
                            # Same zone — check for dwell emit
                            zone_enter_frame = tracker.get_zone_enter_frame(track_id)
                            if zone_enter_frame is not None:
                                frames_in_zone = frame_idx - zone_enter_frame
                                secs_in_zone = frames_in_zone / fps
                                last_dwell = dwell_state.get(visitor_id, {}).get(zone, 0)
                                intervals_passed = int(secs_in_zone / DWELL_EMIT_INTERVAL_SEC)

                                if intervals_passed > last_dwell:
                                    dwell_ms = int(secs_in_zone * 1000)
                                    evt = emit_event(
                                        store_id=store_id,
                                        camera_id=camera_id,
                                        visitor_id=visitor_id,
                                        event_type="ZONE_DWELL",
                                        timestamp=ts_str,
                                        zone_id=zone,
                                        dwell_ms=dwell_ms,
                                        is_staff=is_staff,
                                        confidence=conf,
                                        session_seq=session_seq,
                                        sku_zone=zone,
                                    )
                                    all_events.append(evt)
                                    out_f.write(json.dumps(evt) + "\n")
                                    out_f.flush()
                                    dwell_state.setdefault(visitor_id, {})[zone] = \
                                        intervals_passed

                    # ── billing queue join ─────────────────────────────────
                    if zone == "BILLING_ZONE":
                        q_depth = tracker.get_queue_depth("BILLING_ZONE")
                        if q_depth > 0 and tracker.not_yet_joined_queue(track_id):
                            evt = emit_event(
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type="BILLING_QUEUE_JOIN",
                                timestamp=ts_str,
                                zone_id="BILLING_ZONE",
                                dwell_ms=0,
                                is_staff=is_staff,
                                confidence=conf,
                                session_seq=session_seq,
                                queue_depth=q_depth,
                            )
                            all_events.append(evt)
                            out_f.write(json.dumps(evt) + "\n")
                            out_f.flush()
                            tracker.mark_joined_queue(track_id)

            # Update queue depth based on how many people are in billing zone now
            tracker.update_queue_depth(
                "BILLING_ZONE",
                sum(
                    1 for tid in current_track_ids
                    if tracker.get_zone_by_id(tid) == "BILLING_ZONE"
                )
            )

            # Clean up lost tracks
            tracker.cleanup_lost_tracks(current_track_ids, ts_str, store_id,
                                        camera_id, all_events, out_f)

    cap.release()
    print(f"[detect] Processed {frame_idx} frames → {len(all_events)} events → {output_path}")
    return all_events


def main():
    parser = argparse.ArgumentParser(description="Purplle CCTV detection pipeline")
    parser.add_argument("--video",   required=True,  help="Path to video file")
    parser.add_argument("--store",   required=True,  help="Store ID e.g. STORE_BLR_002")
    parser.add_argument("--camera",  required=True,  help="Camera ID e.g. CAM_ENTRY_01")
    parser.add_argument("--output",  default="data/events/events.jsonl")
    parser.add_argument("--clip-start", default=None,
                        help="ISO-8601 UTC timestamp for frame 0")
    args = parser.parse_args()

    process_video(
        video_path=args.video,
        store_id=args.store,
        camera_id=args.camera,
        output_path=args.output,
        clip_start_time=args.clip_start,
    )


if __name__ == "__main__":
    main()
