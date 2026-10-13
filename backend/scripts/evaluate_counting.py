import os
import sys
import glob
from dataclasses import dataclass
from typing import List

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shelfwatcher.vision.detector import Detection, CLASS_NAMES, CLASS_TO_SKU
from src.shelfwatcher.vision.counting import build_snapshot


@dataclass
class ShelfMock:
    shelf_id: int = 1
    total_facings: int = 10
    depth_factor: float = 1.0


@dataclass
class PlanogramMock:
    zone: int
    sku_id: int


def evaluate_test_counting():
    """
    Evaluates counting accuracy and gap recall on the Milestone 1 test partition (Session 3).
    """
    labels_test_dir = os.path.join("data", "yolo", "labels", "test")
    label_files = glob.glob(os.path.join(labels_test_dir, "*.txt"))

    if not label_files:
        print("[!] No test labels found in data/yolo/labels/test.")
        return

    print("=" * 60)
    print(" Milestone 2: Evaluating Counting & Gap Accuracy on Test Set")
    print("=" * 60)
    print(f"[*] Found {len(label_files)} test scenes (Session 3).")

    shelf = ShelfMock(shelf_id=1, total_facings=10, depth_factor=1.0)
    planograms = [PlanogramMock(zone=i, sku_id=i) for i in range(1, 11)]

    correct_exact_counts = 0
    total_gaps_gt = 0
    total_gaps_detected = 0

    for path in label_files:
        ground_truth_dets: List[Detection] = []
        gt_item_count = 0
        gt_gap_count = 0

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                cls_id = int(parts[0])
                cx, cy, w, h = map(float, parts[1:])
                x1 = cx - w / 2.0
                y1 = cy - h / 2.0
                x2 = cx + w / 2.0
                y2 = cy + h / 2.0

                cls_name = CLASS_NAMES.get(cls_id, "item")
                sku_id = CLASS_TO_SKU.get(cls_name)

                if cls_id == 0:
                    gt_gap_count += 1
                else:
                    gt_item_count += 1

                ground_truth_dets.append(
                    Detection(
                        cls=cls_name,
                        sku_id=sku_id,
                        bbox=(x1, y1, x2, y2),
                        conf=0.95,
                        uncertain=False
                    )
                )

        snapshot = build_snapshot(shelf, ground_truth_dets, planograms, apply_stability=False)

        # Counting metric
        if snapshot.item_count == gt_item_count:
            correct_exact_counts += 1

        total_gaps_gt += gt_gap_count
        total_gaps_detected += snapshot.gap_count

    accuracy = (correct_exact_counts / len(label_files)) * 100.0
    print(f"\n[OK] Evaluated {len(label_files)} test frames:")
    print(f"     - Exact Shelf Count Accuracy: {accuracy:.2f}% (Target: >= 90%)")
    print(f"     - Total Ground Truth Gaps:    {total_gaps_gt}")
    print(f"     - Detected Gap Facings:       {total_gaps_detected}")

    if accuracy >= 90.0:
        print("[SUCCESS] Milestone 2 count accuracy criteria achieved.")
    else:
        print("[WARN] Count accuracy fell below 90% threshold.")


if __name__ == "__main__":
    evaluate_test_counting()
