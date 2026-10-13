import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shelfwatcher.vision.detector import Detection
from src.shelfwatcher.vision.tracker import ShelfTracker
from src.shelfwatcher.vision.events import EventProcessor
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.db.models import DemandSeries, Event


def verify_milestone_4():
    print("=" * 60)
    print(" Milestone 4: Tracking & Events Ground Truth Verification")
    print("=" * 60)

    db = SessionLocal()
    tracker = ShelfTracker(iou_threshold=0.30, miss_tolerance_frames=3, max_buffer_frames=30)
    proc = EventProcessor(shelf_id=1, store_id=1, miss_tolerance_frames=3, putback_window_min=5, refill_delta=30.0)

    start_time = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------
    # Sequence 1: 5 static items over 20 frames (Test ID stability)
    # -------------------------------------------------------------
    print("\n[Sequence 1] Testing static tracking across 20 frames...")
    base_dets = [
        Detection(cls="milk_1l", sku_id=1, bbox=(0.05, 0.2, 0.20, 0.8), conf=0.92),
        Detection(cls="yogurt_500g", sku_id=2, bbox=(0.25, 0.2, 0.40, 0.8), conf=0.91),
        Detection(cls="apple_juice_1l", sku_id=3, bbox=(0.45, 0.2, 0.60, 0.8), conf=0.89),
        Detection(cls="orange_juice_1l", sku_id=4, bbox=(0.65, 0.2, 0.80, 0.8), conf=0.90),
        Detection(cls="white_bread_400g", sku_id=5, bbox=(0.82, 0.2, 0.95, 0.8), conf=0.94),
    ]

    for frame_idx in range(20):
        t = start_time + timedelta(seconds=frame_idx * 15)
        # Add realistic +/- 1px sensor jitter
        jitter_dets = [
            Detection(
                cls=d.cls,
                sku_id=d.sku_id,
                bbox=(d.bbox[0] + 0.001 * (frame_idx % 2), d.bbox[1], d.bbox[2] + 0.001 * (frame_idx % 2), d.bbox[3]),
                conf=d.conf
            )
            for d in base_dets
        ]
        tracks = tracker.update(jitter_dets, zone_count=5, timestamp=t)
        proc.process_frame_tracks(tracks, fill_pct=50.0, gap_count=5, timestamp=t, db_session=db)

    id_switch_rate = tracker.id_switch_rate
    print(f"     -> ID switch rate: {id_switch_rate:.2f}% (Target: < 5.0%)")
    assert id_switch_rate < 5.0, f"ID switch rate {id_switch_rate}% exceeded target"

    # -------------------------------------------------------------
    # Sequence 2: Detection Miss (Miss Tolerance: 2 frames)
    # -------------------------------------------------------------
    print("\n[Sequence 2] Simulating temporary detection dropout (miss tolerance)...")
    t_miss1 = start_time + timedelta(seconds=21 * 15)
    t_miss2 = start_time + timedelta(seconds=22 * 15)

    # Frame 21 & 22: Milk (sku 1) temporarily occluded
    sub_dets = base_dets[1:]
    tr_miss1 = tracker.update(sub_dets, zone_count=5, timestamp=t_miss1)
    evs_m1 = proc.process_frame_tracks(tr_miss1, fill_pct=40.0, gap_count=6, timestamp=t_miss1, db_session=db)

    tr_miss2 = tracker.update(sub_dets, zone_count=5, timestamp=t_miss2)
    evs_m2 = proc.process_frame_tracks(tr_miss2, fill_pct=40.0, gap_count=6, timestamp=t_miss2, db_session=db)

    # Must NOT have triggered an ITEM_REMOVED
    removals_seq2 = [e for e in evs_m1 + evs_m2 if e["type"] == "ITEM_REMOVED"]
    print(f"     -> Removals triggered during 2-frame miss: {len(removals_seq2)} (Expected: 0)")
    assert len(removals_seq2) == 0

    # -------------------------------------------------------------
    # Sequence 3: Put-Back within 3 minutes
    # -------------------------------------------------------------
    print("\n[Sequence 3] Simulating item put-back within window...")
    # Item absent for 4 frames (> 3 miss_tolerance_frames) to enter pending removal
    for f_drop in range(23, 26):
        t_drop = start_time + timedelta(seconds=f_drop * 15)
        tr_drop = tracker.update(sub_dets, zone_count=5, timestamp=t_drop)
        proc.process_frame_tracks(tr_drop, fill_pct=40.0, gap_count=6, timestamp=t_drop, db_session=db)

    # Frame 26: Milk returns after 2.5 minutes (< 5 min putback window)
    t_return = t_miss1 + timedelta(minutes=2.5)
    tr_return = tracker.update(base_dets, zone_count=5, timestamp=t_return)
    evs_return = proc.process_frame_tracks(tr_return, fill_pct=50.0, gap_count=5, timestamp=t_return, db_session=db)

    putbacks = [e for e in evs_return if e["type"] == "PUT_BACK"]
    print(f"     -> Put-back events triggered: {len(putbacks)} (Expected: 1)")
    assert len(putbacks) == 1
    assert putbacks[0]["sku_id"] == 1

    # -------------------------------------------------------------
    # Sequence 4: Confirmed Item Removal (> 5 min window)
    # -------------------------------------------------------------
    print("\n[Sequence 4] Simulating permanent removal exceeding putback window...")
    t_take = t_return + timedelta(seconds=30)
    dets_no_oj = [d for d in base_dets if d.sku_id != 4]

    # Advance 4 frames to exceed miss_tolerance_frames (3)
    for f in range(4):
        t_tick = t_take + timedelta(seconds=f * 15)
        tr_tick = tracker.update(dets_no_oj, zone_count=5, timestamp=t_tick)
        proc.process_frame_tracks(tr_tick, fill_pct=40.0, gap_count=6, timestamp=t_tick, db_session=db)

    # Advance time by 6 minutes (> 5 min putback window)
    t_after_window = t_take + timedelta(minutes=6)
    tr_after = tracker.update(dets_no_oj, zone_count=5, timestamp=t_after_window)
    evs_after = proc.process_frame_tracks(tr_after, fill_pct=40.0, gap_count=6, timestamp=t_after_window, db_session=db)

    confirmed_removals = [e for e in evs_after if e["type"] == "ITEM_REMOVED"]
    print(f"     -> Confirmed ITEM_REMOVED events: {len(confirmed_removals)} (Expected: 1)")
    assert len(confirmed_removals) == 1
    assert confirmed_removals[0]["sku_id"] == 4

    # Check demand_series in database
    hour_slot = t_after_window.replace(minute=0, second=0, microsecond=0)
    ds = db.query(DemandSeries).filter(
        DemandSeries.store_id == 1,
        DemandSeries.sku_id == 4,
        DemandSeries.ts == hour_slot
    ).first()
    print(f"     -> Database demand_series units_removed for SKU 4: {ds.units_removed if ds else 0}")
    assert ds is not None and ds.units_removed >= 1

    # -------------------------------------------------------------
    # Sequence 5: Shelf Refilled (+40% jump)
    # -------------------------------------------------------------
    print("\n[Sequence 5] Simulating shelf replenishment...")
    t_refill = t_after_window + timedelta(minutes=15)
    tr_refill = tracker.update(base_dets, zone_count=5, timestamp=t_refill)
    evs_refill = proc.process_frame_tracks(tr_refill, fill_pct=85.0, gap_count=1, timestamp=t_refill, db_session=db)
    refills = [e for e in evs_refill if e["type"] == "SHELF_REFILLED"]
    print(f"     -> SHELF_REFILLED events: {len(refills)} (Expected: 1)")
    assert len(refills) == 1

    print("\n" + "=" * 60)
    print("[SUCCESS] Milestone 4 criteria fully verified:")
    print(f"  - ID switches < 5% (Actual: {id_switch_rate:.2f}%): PASSED")
    print("  - Miss tolerance: PASSED")
    print("  - Put-back vs Removal separation: PASSED")
    print("  - Confirmed ITEM_REMOVED to demand_series: PASSED")
    print("  - SHELF_REFILLED detection: PASSED")
    print("=" * 60)

    db.close()


if __name__ == "__main__":
    verify_milestone_4()
