import os
import sys

# Ensure repository root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shelfwatcher.simulation.mini_shelf_gen import export_dataset


def main():
    print("=" * 60)
    print(" Milestone 1: Generating Staged Mini-Shelf Dataset")
    print("=" * 60)
    print("[*] Target Classes: 10 Mini-Shelf SKUs + Explicit 'gap' class (0)")
    print("[*] Split Scheme: Session 1 (Train), Session 2 (Val), Session 3 (Test)")

    stats = export_dataset(
        output_base_dir="data/yolo",
        train_count=210,
        val_count=45,
        test_count=45
    )

    total_images = stats["train"] + stats["val"] + stats["test"]
    print(f"\n[OK] Successfully generated {total_images} images across 3 sessions:")
    print(f"     - Train (Session 1): {stats['train']} images")
    print(f"     - Val   (Session 2): {stats['val']} images")
    print(f"     - Test  (Session 3): {stats['test']} images")
    print(f"     - Total Item Bounding Boxes: {stats['items']}")
    print(f"     - Total Gap Bounding Boxes:  {stats['gaps']}")
    print("\nDataset ready for Milestone 2 (Detector + Counting).")


if __name__ == "__main__":
    main()
