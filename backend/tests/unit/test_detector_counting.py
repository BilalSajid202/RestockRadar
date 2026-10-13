from dataclasses import dataclass
from src.shelfwatcher.vision.detector import (
    Detection, compute_iou, apply_nms, CLASS_NAMES, CLASS_TO_SKU
)
from src.shelfwatcher.vision.counting import (
    build_snapshot, StabilityFilter
)


@dataclass
class MockShelf:
    shelf_id: int = 1
    total_facings: int = 10
    depth_factor: float = 1.0


@dataclass
class MockPlanogram:
    zone: int
    sku_id: int


def test_iou_computation():
    boxA = (0.1, 0.1, 0.5, 0.5)
    boxB = (0.1, 0.1, 0.5, 0.5)
    assert compute_iou(boxA, boxB) == 1.0

    boxC = (0.6, 0.6, 0.9, 0.9)
    assert compute_iou(boxA, boxC) == 0.0


def test_nms_suppression():
    dets = [
        Detection(cls="milk_1l", sku_id=1, bbox=(0.1, 0.1, 0.4, 0.4), conf=0.9),
        Detection(cls="milk_1l", sku_id=1, bbox=(0.11, 0.11, 0.41, 0.41), conf=0.6),  # should be suppressed
        Detection(cls="gap", sku_id=None, bbox=(0.5, 0.1, 0.8, 0.4), conf=0.85),
    ]
    kept = apply_nms(dets, iou_threshold=0.5)
    assert len(kept) == 2
    assert kept[0].conf == 0.9
    assert kept[1].cls == "gap"


def test_build_snapshot_counts_and_fill():
    shelf = MockShelf(shelf_id=1, total_facings=10, depth_factor=1.0)
    planograms = [
        MockPlanogram(zone=1, sku_id=1),  # Zone 1 expects Milk
        MockPlanogram(zone=2, sku_id=2),  # Zone 2 expects Yogurt
    ]

    # 1 Milk detection in zone 1, 1 gap detection in zone 2
    detections = [
        Detection(cls="milk_1l", sku_id=1, bbox=(0.1, 0.2, 0.4, 0.8), conf=0.85),
        Detection(cls="gap", sku_id=None, bbox=(0.6, 0.2, 0.9, 0.8), conf=0.80),
        Detection(cls="milk_1l", sku_id=1, bbox=(0.2, 0.2, 0.3, 0.5), conf=0.20, uncertain=True),  # uncertain
    ]

    snapshot = build_snapshot(shelf, detections, planograms, apply_stability=False)
    assert snapshot.item_count == 1  # Uncertain excluded
    assert snapshot.gap_count >= 1
    assert 0.0 <= snapshot.fill_pct <= 100.0
    assert snapshot.item_counts_by_sku.get(1) == 1


def test_misplaced_item_detection():
    shelf = MockShelf(shelf_id=1, total_facings=2, depth_factor=1.0)
    # Zone 1 (0.0 to 0.5) expects Milk (sku 1)
    # Zone 2 (0.5 to 1.0) expects Yogurt (sku 2)
    planograms = [
        MockPlanogram(zone=1, sku_id=1),
        MockPlanogram(zone=2, sku_id=2)
    ]

    # Detected Yogurt placed in Zone 1 (x center is 0.25)
    detections = [
        Detection(cls="yogurt_500g", sku_id=2, bbox=(0.1, 0.2, 0.4, 0.8), conf=0.88)
    ]

    snapshot = build_snapshot(shelf, detections, planograms, apply_stability=False)
    assert len(snapshot.misplaced_items) == 1
    assert snapshot.misplaced_items[0]["detected_sku"] == 2
    assert snapshot.misplaced_items[0]["expected_sku"] == 1


def test_stability_filter():
    filt = StabilityFilter(n_consistent=2)

    # Initial frame
    s1 = filt.update(shelf_id=1, state_signature="OK")
    assert s1 == "OK"

    # Single transient fluctuation to LOW should not immediately change accepted status
    s2 = filt.update(shelf_id=1, state_signature="LOW")
    assert s2 == "OK"

    # Second consecutive LOW frame confirms the transition
    s3 = filt.update(shelf_id=1, state_signature="LOW")
    assert s3 == "LOW"
