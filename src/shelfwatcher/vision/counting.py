from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timezone
import numpy as np

from src.shelfwatcher.vision.detector import Detection, compute_iou
from src.shelfwatcher.config import settings
from src.shelfwatcher import clock


@dataclass
class ShelfSnapshotResult:
    shelf_id: int
    sku_id: Optional[int]
    captured_at: datetime
    item_count: int
    gap_count: int
    fill_pct: float
    estimated: bool
    status: str  # OK, LOW, EMPTY, UNKNOWN
    item_counts_by_sku: Dict[int, int] = field(default_factory=dict)
    misplaced_items: List[Dict[str, Any]] = field(default_factory=list)


class StabilityFilter:
    """
    Accepts a state change (such as fill status or gap count) only after
    N_CONSISTENT (default 2) consecutive identical frames per shelf.
    """

    def __init__(self, n_consistent: int = settings.n_consistent):
        self.n_consistent = n_consistent
        self._history: Dict[int, List[str]] = {}  # shelf_id -> list of state signatures
        self._current_accepted: Dict[int, str] = {}

    def update(self, shelf_id: int, state_signature: str) -> str:
        """
        Takes the current observed state signature for a shelf,
        and returns the accepted filtered state signature.
        """
        if shelf_id not in self._history:
            self._history[shelf_id] = [state_signature]
            self._current_accepted[shelf_id] = state_signature
            return state_signature

        history = self._history[shelf_id]
        history.append(state_signature)

        # Keep only the last n_consistent entries
        if len(history) > self.n_consistent:
            history.pop(0)

        # If all recent observations are identical, accept the state
        if len(history) == self.n_consistent and all(s == state_signature for s in history):
            self._current_accepted[shelf_id] = state_signature

        return self._current_accepted[shelf_id]


# Global stability filter instance
global_stability_filter = StabilityFilter(n_consistent=settings.n_consistent)


def build_snapshot(
    shelf: Any,
    detections: List[Detection],
    planograms: List[Any],
    apply_stability: bool = True
) -> ShelfSnapshotResult:
    """
    Computes item counts, gap counts, fill percentage, depth estimation, and misplaced items
    according to context.md Section 9.3.
    """
    shelf_id = getattr(shelf, "shelf_id", 1)
    total_facings = getattr(shelf, "total_facings", 10) or 10
    depth_factor = float(getattr(shelf, "depth_factor", 1.0) or 1.0)
    now_ts = clock.now()

    # Filter out uncertain detections from counts
    confident_detections = [d for d in detections if not d.uncertain]

    # Map planogram zones: zone_index -> expected sku_id, facings
    # In normalized ROI coordinates, slice shelf horizontally into zones
    zone_count = max(len(planograms), 1)
    zone_width = 1.0 / zone_count

    expected_zones: Dict[int, int] = {}  # zone_index -> sku_id
    for pl in planograms:
        z_idx = getattr(pl, "zone", 1) - 1  # 0-indexed zone
        expected_zones[z_idx] = getattr(pl, "sku_id", None)

    item_counts_by_sku: Dict[int, int] = {}
    misplaced_items: List[Dict[str, Any]] = []
    occupied_zones: set = set()

    # Separate items and explicit gaps
    item_dets = [d for d in confident_detections if d.cls != "gap" and d.cls != "person"]
    gap_dets = [d for d in confident_detections if d.cls == "gap"]

    for det in item_dets:
        # Determine center x in normalized coordinates
        cx = (det.bbox[0] + det.bbox[2]) / 2.0
        zone_idx = min(int(cx / zone_width), zone_count - 1)

        # Check if SKU is misplaced
        expected_sku = expected_zones.get(zone_idx)
        if expected_sku is not None and det.sku_id is not None and det.sku_id != expected_sku:
            misplaced_items.append({
                "detected_sku": det.sku_id,
                "expected_sku": expected_sku,
                "zone": zone_idx + 1,
                "bbox": det.bbox
            })

        # Count item
        if det.sku_id is not None:
            item_counts_by_sku[det.sku_id] = item_counts_by_sku.get(det.sku_id, 0) + 1
            occupied_zones.add(zone_idx)

    # Depth estimation
    estimated = False
    total_visible_front = sum(item_counts_by_sku.values())
    if depth_factor > 1.0:
        total_items = int(round(total_visible_front * depth_factor))
        estimated = True
    else:
        total_items = total_visible_front

    # Gap count logic: union of detected gaps and planogram facings with no item
    # De-duplicated by IoU > 0.3
    unique_gaps = []
    for g in gap_dets:
        is_dup = False
        for ug in unique_gaps:
            if compute_iou(g.bbox, ug.bbox) > 0.30:
                is_dup = True
                break
        if not is_dup:
            unique_gaps.append(g)

    # Empty planogram zones count
    empty_planogram_zones = zone_count - len(occupied_zones)
    gap_count = max(len(unique_gaps), empty_planogram_zones)

    # Fill percentage bounded [0, 100]
    occupied_facings = min(total_facings, max(0, total_facings - gap_count))
    fill_pct = (occupied_facings / float(total_facings)) * 100.0
    fill_pct = max(0.0, min(100.0, fill_pct))

    # Raw status
    if fill_pct == 0.0:
        raw_status = "EMPTY"
    elif fill_pct < 30.0:
        raw_status = "LOW"
    else:
        raw_status = "OK"

    # Stability filter application
    if apply_stability:
        accepted_status = global_stability_filter.update(shelf_id, raw_status)
    else:
        accepted_status = raw_status

    return ShelfSnapshotResult(
        shelf_id=shelf_id,
        sku_id=None,
        captured_at=now_ts,
        item_count=total_items,
        gap_count=gap_count,
        fill_pct=round(fill_pct, 2),
        estimated=estimated,
        status=accepted_status,
        item_counts_by_sku=item_counts_by_sku,
        misplaced_items=misplaced_items
    )
