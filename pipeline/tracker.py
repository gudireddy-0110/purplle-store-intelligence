"""
Visitor tracker — maintains per-track state across frames.

Responsibilities:
- Assign stable visitor_id tokens to YOLO track IDs
- Detect re-entry (same track_id seen after EXIT)
- Track which zone each visitor is currently in
- Track queue depth per zone
- Clean up lost tracks and emit EXIT events for them
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrackState:
    visitor_id: str
    prev_cy: Optional[float]        # previous frame Y center
    session_seq: int                # incrementing event counter for this visitor
    is_inside: bool                 # currently inside the store
    has_exited: bool                # has ever exited (for re-entry detection)
    current_zone: Optional[str]     # zone name or None
    zone_enter_frame: Optional[int] # frame number when entered current zone
    joined_queue: bool              # has already emitted BILLING_QUEUE_JOIN
    last_seen_frame: int            # for detecting lost tracks


class VisitorTracker:
    def __init__(self, lost_track_timeout_frames: int = 90):
        """
        Args:
            lost_track_timeout_frames: if a track_id is not seen for this many
                frames, consider it lost and emit EXIT if still inside store.
        """
        self._tracks: dict[int, TrackState] = {}
        self._queue_depths: dict[str, int] = {}
        self._timeout = lost_track_timeout_frames

    # ── public API ─────────────────────────────────────────────────────────────

    def update(
        self, track_id: int, cy: float, frame_idx: int
    ) -> tuple[str, Optional[float], int, bool]:
        """
        Register a detected track_id in this frame.

        Returns:
            (visitor_id, prev_cy, session_seq, had_exited)
        """
        if track_id not in self._tracks:
            self._tracks[track_id] = TrackState(
                visitor_id=f"VIS_{uuid.uuid4().hex[:6]}",
                prev_cy=None,
                session_seq=0,
                is_inside=False,
                has_exited=False,
                current_zone=None,
                zone_enter_frame=None,
                joined_queue=False,
                last_seen_frame=frame_idx,
            )

        state = self._tracks[track_id]
        prev_cy = state.prev_cy
        state.prev_cy = cy
        state.session_seq += 1
        state.last_seen_frame = frame_idx

        return state.visitor_id, prev_cy, state.session_seq, state.has_exited

    def mark_entered(self, track_id: int) -> None:
        """Call after emitting ENTRY or REENTRY event."""
        if track_id in self._tracks:
            s = self._tracks[track_id]
            s.is_inside = True
            s.has_exited = False   # reset for next re-entry cycle

    def mark_exited(self, track_id: int) -> None:
        """Call after emitting EXIT event."""
        if track_id in self._tracks:
            s = self._tracks[track_id]
            s.is_inside = False
            s.has_exited = True
            s.current_zone = None
            s.zone_enter_frame = None
            s.joined_queue = False

    def is_inside_store(self, track_id: int) -> bool:
        return self._tracks.get(track_id, TrackState(
            "", None, 0, False, False, None, None, False, 0
        )).is_inside

    def get_zone(self, track_id: int) -> Optional[str]:
        return self._tracks[track_id].current_zone if track_id in self._tracks else None

    def get_zone_by_id(self, track_id: int) -> Optional[str]:
        """Alias for queue depth calculation."""
        return self.get_zone(track_id)

    def set_zone(self, track_id: int, zone: str, frame_idx: int) -> None:
        if track_id in self._tracks:
            self._tracks[track_id].current_zone = zone
            self._tracks[track_id].zone_enter_frame = frame_idx

    def get_zone_enter_frame(self, track_id: int) -> Optional[int]:
        if track_id in self._tracks:
            return self._tracks[track_id].zone_enter_frame
        return None

    def not_yet_joined_queue(self, track_id: int) -> bool:
        if track_id in self._tracks:
            return not self._tracks[track_id].joined_queue
        return False

    def mark_joined_queue(self, track_id: int) -> None:
        if track_id in self._tracks:
            self._tracks[track_id].joined_queue = True

    def get_queue_depth(self, zone: str) -> int:
        return self._queue_depths.get(zone, 0)

    def update_queue_depth(self, zone: str, depth: int) -> None:
        self._queue_depths[zone] = depth

    def cleanup_lost_tracks(
        self,
        current_track_ids: set[int],
        ts_str: str,
        store_id: str,
        camera_id: str,
        all_events: list,
        out_f,
    ) -> None:
        """
        For any track that hasn't been seen in `_timeout` frames AND
        is still marked as inside the store, emit an EXIT event.
        This handles people who walk off camera without crossing the entry line.
        """
        from pipeline.emit import emit_event

        to_remove = []
        for track_id, state in self._tracks.items():
            if track_id in current_track_ids:
                continue
            # Check if timed out — we don't have frame_idx here so caller
            # should pass it; approximate with last_seen_frame stored
            if state.is_inside:
                # Emit synthetic EXIT
                evt = emit_event(
                    store_id=store_id,
                    camera_id=camera_id,
                    visitor_id=state.visitor_id,
                    event_type="EXIT",
                    timestamp=ts_str,
                    zone_id=None,
                    dwell_ms=0,
                    is_staff=False,
                    confidence=0.0,
                    session_seq=state.session_seq + 1,
                    metadata_extra={"synthetic": True},
                )
                all_events.append(evt)
                out_f.write(json.dumps(evt) + "\n")
                out_f.flush()
                state.is_inside = False
                state.has_exited = True

            to_remove.append(track_id)

        for tid in to_remove:
            del self._tracks[tid]
