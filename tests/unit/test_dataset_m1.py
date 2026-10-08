import os
import yaml
import pytest


def test_data_yaml_structure():
    yaml_path = os.path.join("data", "yolo", "data.yaml")
    assert os.path.exists(yaml_path), "data/yolo/data.yaml must exist"

    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert "names" in config, "data.yaml must contain 'names' dictionary"
    assert config["names"][0] == "gap", "Class 0 must be 'gap'"
    assert config["nc"] == len(config["names"]), "nc must match number of classes"
    assert "train" in config and "val" in config and "test" in config


def test_m1_dataset_integrity():
    base_dir = os.path.join("data", "yolo")
    splits = ["train", "val", "test"]

    split_files = {}
    gap_count = 0
    total_boxes = 0

    for split in splits:
        img_dir = os.path.join(base_dir, "images", split)
        lbl_dir = os.path.join(base_dir, "labels", split)

        assert os.path.exists(img_dir), f"{img_dir} directory missing"
        assert os.path.exists(lbl_dir), f"{lbl_dir} directory missing"

        images = set(f for f in os.listdir(img_dir) if f.endswith(".jpg"))
        labels = set(f for f in os.listdir(lbl_dir) if f.endswith(".txt"))

        # Verify 1-to-1 match between images and labels
        img_stems = {os.path.splitext(f)[0] for f in images}
        lbl_stems = {os.path.splitext(f)[0] for f in labels}
        assert img_stems == lbl_stems, f"Mismatch between images and labels in {split}"

        split_files[split] = img_stems

        # Validate bounding box coordinates
        for lbl_file in labels:
            with open(os.path.join(lbl_dir, lbl_file), "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    cls_id = int(parts[0])
                    cx, cy, w, h = map(float, parts[1:])

                    # Coordinates must be strictly in [0, 1]
                    assert 0.0 <= cx <= 1.0, f"cx out of bounds in {lbl_file}: {cx}"
                    assert 0.0 <= cy <= 1.0, f"cy out of bounds in {lbl_file}: {cy}"
                    assert 0.0 < w <= 1.0, f"width out of bounds in {lbl_file}: {w}"
                    assert 0.0 < h <= 1.0, f"height out of bounds in {lbl_file}: {h}"

                    total_boxes += 1
                    if cls_id == 0:
                        gap_count += 1

    # Anti-leakage assertion: No image stem appears in more than one split
    assert len(split_files["train"].intersection(split_files["val"])) == 0
    assert len(split_files["train"].intersection(split_files["test"])) == 0
    assert len(split_files["val"].intersection(split_files["test"])) == 0

    # Verify session-based segregation
    assert all(stem.startswith("session1_") for stem in split_files["train"])
    assert all(stem.startswith("session2_") for stem in split_files["val"])
    assert all(stem.startswith("session3_") for stem in split_files["test"])

    # Milestone 1 acceptance criteria: Few hundred labelled images, gaps labelled
    total_images = sum(len(s) for s in split_files.values())
    assert total_images >= 300, f"Expected at least 300 images, got {total_images}"
    assert gap_count > 0, "Explicit gap annotations must be present"
    assert total_boxes > total_images, "Each image should have multiple annotations"
