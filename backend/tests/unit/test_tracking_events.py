from datetime import datetime, timezone, timedelta
import pytest

from src.shelfwatcher.vision.detector import Detection
from src.shelfwatcher.vision.tracker import ShelfTracker
from src.shelfwatcher.vision.events import EventProcessor


def test_tracker_maintains_stable_ids():
    tracker = ShelfTracker(iou_threshold=0.3)
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)

    # 3 static items
    dets = [
        Detection(cls="milk_1l", sku_id=1, bbox=(0.1, 0.2, 0.3, 0.8), conf=0.9),
        Detection(cls="yogurt_500g", sku_id=2, bbox=(0.4, 0.2, 0.6, 0.8), conf=0.9),
        Detection(cls="apple_juice_1l", sku_id=3, bbox=(0.7, 0.2, 0.9, 0.8), conf=0.9),
    ]

    # Frame 1
    tracks1 = tracker.update(dets, zone_count=3, timestamp=t0)
    assert len(tracks1) == 3
    initial_ids = {t.track_id for t in tracks1}

    # Frame 2 to 5 with slight pixel jitter
    for f in range(1, 5):
        tf = t0 + timedelta(seconds=f * 5)
        jitter_dets = [
            Detection(cls=d.cls, sku_id=d.sku_id, bbox=(d.bbox[0] + 0.002, d.bbox[1], d.bbox[2] + 0.002, d.bbox[3]), conf=0.9)
            for d in dets
        ]
        tracks = tracker.update(jitter_dets, zone_count=3, timestamp=tf)
        current_ids = {t.track_id for t in tracks}
        assert current_ids == initial_ids, f"Track IDs must remain identical across frames: {current_ids} vs {initial_ids}"

    assert tracker.id_switch_rate < 5.0


def test_miss_tolerance_no_false_removal():
    tracker = ShelfTracker(miss_tolerance_frames=3)
    proc = EventProcessor(shelf_id=1, miss_tolerance_frames=3, putback_window_min=5)
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)

    det = Detection(cls="milk_1l", sku_id=1, bbox=(0.1, 0.2, 0.3, 0.8), conf=0.9)

    # Frame 1: item present
    tr1 = tracker.update([det], zone_count=1, timestamp=t0)
    proc.process_frame_tracks(tr1, fill_pct=100.0, gap_count=0, timestamp=t0)

    # Frame 2: temporary detection drop (missed 1 frame)
    t1 = t0 + timedelta(seconds=15)
    tr2 = tracker.update([], zone_count=1, timestamp=t1)
    evs2 = proc.process_frame_tracks(tr2, fill_pct=100.0, gap_count=0, timestamp=t1)

    # Should NOT trigger ITEM_REMOVED (within miss tolerance)
    removal_events = [e for e in evs2 if e["type"] == "ITEM_REMOVED"]
    assert len(removal_events) == 0


def test_putback_resolution():
    tracker = ShelfTracker(miss_tolerance_frames=1)
    proc = EventProcessor(shelf_id=1, miss_tolerance_frames=1, putback_window_min=5)
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)

    det = Detection(cls="milk_1l", sku_id=1, bbox=(0.1, 0.2, 0.3, 0.8), conf=0.9)

    # Frame 1: Present
    tr1 = tracker.update([det], zone_count=1, timestamp=t0)
    proc.process_frame_tracks(tr1, fill_pct=100.0, gap_count=0, timestamp=t0)

    # Frame 2: Missing (customer picked it up)
    t1 = t0 + timedelta(seconds=30)
    tr2 = tracker.update([], zone_count=1, timestamp=t1)
    proc.process_frame_tracks(tr2, fill_pct=0.0, gap_count=1, timestamp=t1)

    # Frame 3: Customer puts it back 2 minutes later (< 5 min putback window)
    t2 = t0 + timedelta(minutes=2)
    tr3 = tracker.update([det], zone_count=1, timestamp=t2)
    evs3 = proc.process_frame_tracks(tr3, fill_pct=100.0, gap_count=0, timestamp=t2)

    # Must generate PUT_BACK and NOT ITEM_REMOVED
    putback_events = [e for e in evs3 if e["type"] == "PUT_BACK"]
    removal_events = [e for e in evs3 if e["type"] == "ITEM_REMOVED"]
    assert len(putback_events) == 1
    assert len(removal_events) == 0


def test_confirmed_item_removal():
    tracker = ShelfTracker(miss_tolerance_frames=1)
    proc = EventProcessor(shelf_id=1, miss_tolerance_frames=1, putback_window_min=5)
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)

    det = Detection(cls="milk_1l", sku_id=1, bbox=(0.1, 0.2, 0.3, 0.8), conf=0.9)

    # Frame 1: Present
    tr1 = tracker.update([det], zone_count=1, timestamp=t0)
    proc.process_frame_tracks(tr1, fill_pct=100.0, gap_count=0, timestamp=t0)

    # Frame 2: Missing
    t1 = t0 + timedelta(seconds=30)
    tr2 = tracker.update([], zone_count=1, timestamp=t1)
    proc.process_frame_tracks(tr2, fill_pct=0.0, gap_count=1, timestamp=t1)

    # Frame 3: Still missing after 6 minutes (> 5 min putback window)
    t2 = t0 + timedelta(minutes=6)
    tr3 = tracker.update([], zone_count=1, timestamp=t2)
    evs3 = proc.process_frame_tracks(tr3, fill_pct=0.0, gap_count=1, timestamp=t2)

    # Must generate confirmed ITEM_REMOVED
    removal_events = [e for e in evs3 if e["type"] == "ITEM_REMOVED"]
    assert len(removal_events) == 1
    assert removal_events[0]["sku_id"] == 1


def test_shelf_refill_and_gap_events():
    proc = EventProcessor(shelf_id=1, refill_delta=30.0)
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)

    # Initial depleted state
    proc.process_frame_tracks([], fill_pct=20.0, gap_count=8, timestamp=t0)

    # Frame 2: Refilled to 85% (+65% jump >= 30%)
    t1 = t0 + timedelta(minutes=15)
    evs = proc.process_frame_tracks([], fill_pct=85.0, gap_count=2, timestamp=t1)

    refill_events = [e for e in evs if e["type"] == "SHELF_REFILLED"]
    gap_closed_events = [e for e in evs if e["type"] == "GAP_CLOSED"]
    assert len(refill_events) == 1
    assert len(gap_closed_events) == 1
