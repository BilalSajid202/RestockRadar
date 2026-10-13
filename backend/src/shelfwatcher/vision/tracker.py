from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set
import numpy as np

from src.shelfwatcher.vision.detector import Detection, compute_iou
from src.shelfwatcher.config import settings
from src.shelfwatcher import clock


@dataclass
class Track:
    track_id: int
    cls: str
    sku_id: Optional[int]
    bbox: Tuple[float, float, float, float]
    zone_idx: int
    first_seen: datetime
    last_seen: datetime
    absent_frames: int = 0
    state: str = "ACTIVE"  # ACTIVE, MISSED, REMOVED, PUT_BACK
    confidence: float = 1.0


class ShelfTracker:
    """
    Persistent tracker optimized for static retail shelf items (context.md Section 9.4).
    Uses high track buffering and IoU matching to maintain persistent identity across frames.
    """

    def __init__(
        self,
        iou_threshold: float = 0.30,
        miss_tolerance_frames: int = settings.miss_tolerance_frames,
        max_buffer_frames: int = 30
    ):
        self.iou_threshold = iou_threshold
        self.miss_tolerance_frames = miss_tolerance_frames
        self.max_buffer_frames = max_buffer_frames
        self._next_id = 1
        self.tracks: Dict[int, Track] = {}
        self.id_switch_count = 0
        self.total_matches = 0

    def reset(self):
        """Resets all active tracks (e.g. camera move or planogram change)."""
        self.tracks.clear()
        self._next_id = 1
        self.id_switch_count = 0
        self.total_matches = 0

    def update(
        self,
        detections: List[Detection],
        zone_count: int = 5,
        timestamp: Optional[datetime] = None
    ) -> List[Track]:
        """
        Updates persistent tracks with confident item detections in the current frame.
        Excludes gap and person detections.
        """
        if timestamp is None:
            timestamp = clock.now()

        # Filter for confident product items only
        item_dets = [d for d in detections if d.cls != "gap" and d.cls != "person" and not d.uncertain]

        active_track_ids = [t_id for t_id, t in self.tracks.items() if t.state in ("ACTIVE", "MISSED")]
        matched_tracks: Set[int] = set()
        matched_dets: Set[int] = set()

        if active_track_ids and item_dets:
            # Build IoU cost matrix
            cost_matrix = np.zeros((len(active_track_ids), len(item_dets)), dtype=float)
            for i, t_id in enumerate(active_track_ids):
                t = self.tracks[t_id]
                for j, d in enumerate(item_dets):
                    # Same class affinity preference
                    base_iou = compute_iou(t.bbox, d.bbox)
                    if t.cls == d.cls:
                        cost_matrix[i, j] = base_iou
                    else:
                        cost_matrix[i, j] = base_iou * 0.5

            # Greedy bipartite matching
            while True:
                max_val = np.max(cost_matrix)
                if max_val < self.iou_threshold:
                    break
                i, j = np.unravel_index(np.argmax(cost_matrix), cost_matrix.shape)
                t_id = active_track_ids[i]

                # Record match
                matched_tracks.add(t_id)
                matched_dets.add(j)

                t = self.tracks[t_id]
                d = item_dets[j]

                # Check for class identity switch
                if t.cls != d.cls:
                    self.id_switch_count += 1
                self.total_matches += 1

                # Update existing track
                t.bbox = d.bbox
                t.confidence = d.conf
                t.last_seen = timestamp
                t.absent_frames = 0
                t.state = "ACTIVE"
                t.zone_idx = min(int(((d.bbox[0] + d.bbox[2]) / 2.0) * zone_count), zone_count - 1)

                # Invalidate matched row and col
                cost_matrix[i, :] = -1.0
                cost_matrix[:, j] = -1.0

        # Increment absence for unmatched tracks
        unmatched_track_ids = set(active_track_ids) - matched_tracks
        for t_id in unmatched_track_ids:
            t = self.tracks[t_id]
            t.absent_frames += 1
            if t.absent_frames >= self.miss_tolerance_frames:
                t.state = "MISSED"

        # Create new tracks for unmatched detections
        zone_width = 1.0 / max(1, zone_count)
        for j, d in enumerate(item_dets):
            if j not in matched_dets:
                cx = (d.bbox[0] + d.bbox[2]) / 2.0
                zone_idx = min(int(cx / zone_width), zone_count - 1)

                new_track = Track(
                    track_id=self._next_id,
                    cls=d.cls,
                    sku_id=d.sku_id,
                    bbox=d.bbox,
                    zone_idx=zone_idx,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    absent_frames=0,
                    state="ACTIVE",
                    confidence=d.conf
                )
                self.tracks[self._next_id] = new_track
                self._next_id += 1

        # Prune very old tracks exceeding max_buffer_frames
        dead_tracks = [t_id for t_id, t in self.tracks.items() if t.absent_frames > self.max_buffer_frames]
        for t_id in dead_tracks:
            del self.tracks[t_id]

        return [t for t in self.tracks.values() if t.state in ("ACTIVE", "MISSED")]

    @property
    def id_switch_rate(self) -> float:
        if self.total_matches == 0:
            return 0.0
        return (self.id_switch_count / self.total_matches) * 100.0
