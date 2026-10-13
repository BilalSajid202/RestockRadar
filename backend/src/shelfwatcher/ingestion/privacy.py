from typing import List, Tuple, Optional
import numpy as np
import cv2

from src.shelfwatcher.vision.detector import Detection


def blur_bounding_box(image: np.ndarray, box_norm: Tuple[float, float, float, float], kernel_size: int = 51) -> np.ndarray:
    """
    Applies heavy Gaussian blur to a normalized bounding box (x1, y1, x2, y2).
    """
    if image is None or image.size == 0:
        return image

    h, w = image.shape[:2]
    x1 = max(0, min(w - 1, int(box_norm[0] * w)))
    y1 = max(0, min(h - 1, int(box_norm[1] * h)))
    x2 = max(0, min(w, int(box_norm[2] * w)))
    y2 = max(0, min(h, int(box_norm[3] * h)))

    if x2 <= x1 or y2 <= y1:
        return image

    roi = image[y1:y2, x1:x2]
    # Ensure kernel size is odd and valid for the ROI dimensions
    k = min(kernel_size, (x2 - x1) | 1, (y2 - y1) | 1)
    if k < 3:
        k = 3
    if k % 2 == 0:
        k += 1

    blurred_roi = cv2.GaussianBlur(roi, (k, k), 30)
    image[y1:y2, x1:x2] = blurred_roi
    return image


def anonymize_frame(image: np.ndarray, person_detections: List[Detection]) -> np.ndarray:
    """
    Gaussian-blurs all detected person regions before saving or displaying (context.md Section 9.1).
    """
    if image is None or image.size == 0 or not person_detections:
        return image

    output = image.copy()
    for det in person_detections:
        if det.cls == "person":
            output = blur_bounding_box(output, det.bbox)

    return output
