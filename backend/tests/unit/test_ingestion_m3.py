import os
import numpy as np
import cv2
import pytest
from datetime import datetime

from src.shelfwatcher.ingestion.base import Frame, crop_roi
from src.shelfwatcher.ingestion.quality import QualityGate, check_quality
from src.shelfwatcher.ingestion.privacy import anonymize_frame, blur_bounding_box
from src.shelfwatcher.ingestion.replay import ReplaySource
from src.shelfwatcher.vision.detector import Detection


def test_quality_gate_valid_frame():
    # Create synthetic textured image with good brightness and variance
    img = np.random.randint(80, 180, (400, 400, 3), dtype=np.uint8)
    # Add strong edges
    img[100:300, 100:300] = 220
    img[150:250, 150:250] = 50

    res = check_quality(img)
    assert res.valid_flag is True, f"Expected valid frame, got error: {res.failure_reason}"
    assert 40 <= res.brightness <= 230
    assert res.blur_variance >= 50


def test_quality_gate_dark_frame():
    # Very dark image: mean brightness < 40
    img = np.full((300, 300, 3), 20, dtype=np.uint8)
    res = check_quality(img)
    assert res.valid_flag is False
    assert "too dark" in res.failure_reason.lower()


def test_quality_gate_blurry_frame():
    # Completely flat, featureless image: Laplacian variance ~ 0
    img = np.full((300, 300, 3), 120, dtype=np.uint8)
    res = check_quality(img)
    assert res.valid_flag is False
    assert "blurry" in res.failure_reason.lower() or "blocked" in res.failure_reason.lower()


def test_quality_gate_blocked_identical_pixels():
    # 80% identical black pixels
    img = np.full((200, 200, 3), 100, dtype=np.uint8)
    img[0:40, :] = 150  # only 20% non-identical
    res = check_quality(img)
    assert res.valid_flag is False


def test_privacy_person_blurring():
    img = np.zeros((300, 300, 3), dtype=np.uint8)
    # Draw a sharp checkerboard pattern inside person box
    img[50:150, 50:150, :] = 255
    img[75:125, 75:125, :] = 0

    person_det = Detection(
        cls="person",
        sku_id=None,
        bbox=(50/300.0, 50/300.0, 150/300.0, 150/300.0),
        conf=0.9
    )

    blurred = anonymize_frame(img, [person_det])
    # The blurred area must no longer be identical to original sharp edges
    diff = np.abs(img.astype(float) - blurred.astype(float))
    assert np.max(diff) > 0, "Gaussian blur must modify pixel values in the person box"


def test_replay_source_reads_files(tmp_path):
    # Create temporary replay folder with two sample frames
    d = tmp_path / "replay_test"
    d.mkdir()

    img1 = np.full((100, 100, 3), 100, dtype=np.uint8)
    img2 = np.full((100, 100, 3), 150, dtype=np.uint8)

    cv2.imwrite(str(d / "20261008_100000.jpg"), img1)
    cv2.imwrite(str(d / "20261008_101500.jpg"), img2)

    source = ReplaySource(folder_path=str(d), camera_id=1, loop=False)

    f1 = source.next_frame()
    assert f1 is not None
    assert f1.camera_id == 1
    assert f1.image.shape == (100, 100, 3)

    f2 = source.next_frame()
    assert f2 is not None

    f3 = source.next_frame()
    assert f3 is None  # loop=False


def test_crop_roi():
    img = np.ones((500, 500, 3), dtype=np.uint8) * 50
    # Center region marked 200
    img[100:300, 100:400] = 200

    polygon = [[100, 100], [399, 100], [399, 299], [100, 299]]
    cropped = crop_roi(img, polygon)

    assert cropped.shape == (200, 300, 3)
    assert np.all(cropped == 200)
