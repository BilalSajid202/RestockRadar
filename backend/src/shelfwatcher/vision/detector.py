from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
import os
import yaml
import numpy as np

from src.shelfwatcher.config import settings

# Load class mapping from data.yaml (single source of truth)
DATA_YAML_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "yolo", "data.yaml")

CLASS_NAMES: Dict[int, str] = {
    0: "gap",
    1: "milk_1l",
    2: "yogurt_500g",
    3: "apple_juice_1l",
    4: "orange_juice_1l",
    5: "white_bread_400g",
    6: "corn_flakes_375g",
    7: "cooking_oil_1l",
    8: "basmati_rice_1kg",
    9: "tomato_ketchup_500g",
    10: "black_tea_400g",
    11: "person"
}

# SKU ID mapping (gap and person are None)
CLASS_TO_SKU: Dict[str, Optional[int]] = {
    "gap": None,
    "milk_1l": 1,
    "yogurt_500g": 2,
    "apple_juice_1l": 3,
    "orange_juice_1l": 4,
    "white_bread_400g": 5,
    "corn_flakes_375g": 6,
    "cooking_oil_1l": 7,
    "basmati_rice_1kg": 8,
    "tomato_ketchup_500g": 9,
    "black_tea_400g": 10,
    "person": None
}


@dataclass
class Detection:
    cls: str
    sku_id: Optional[int]
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2) normalized in [0.0, 1.0]
    conf: float
    uncertain: bool = False
    model_version: str = "v1"

    @property
    def area(self) -> float:
        w = max(0.0, self.bbox[2] - self.bbox[0])
        h = max(0.0, self.bbox[3] - self.bbox[1])
        return w * h


def compute_iou(boxA: Tuple[float, float, float, float], boxB: Tuple[float, float, float, float]) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    inter_w = max(0.0, xB - xA)
    inter_h = max(0.0, yB - yA)
    inter_area = inter_w * inter_h

    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union_area = areaA + areaB - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def apply_nms(detections: List[Detection], iou_threshold: float = 0.50) -> List[Detection]:
    """Applies Non-Maximum Suppression within identical detection classes."""
    if not detections:
        return []

    # Sort descending by confidence
    sorted_dets = sorted(detections, key=lambda d: d.conf, reverse=True)
    kept: List[Detection] = []

    for det in sorted_dets:
        suppress = False
        for k in kept:
            if det.cls == k.cls and compute_iou(det.bbox, k.bbox) > iou_threshold:
                suppress = True
                break
        if not suppress:
            kept.append(det)

    return kept


class ShelfDetector:
    """
    YOLOv8-based detector interface with support for PyTorch weights and fallback.
    """

    def __init__(self, weights_path: Optional[str] = None):
        self.weights_path = weights_path
        self.model = None
        self.model_version = "v1"

        if weights_path and os.path.exists(weights_path):
            try:
                from ultralytics import YOLO
                self.model = YOLO(weights_path)
            except Exception:
                self.model = None

    def detect(
        self,
        roi_image: np.ndarray,
        conf: float = settings.conf_threshold,
        uncertain_thresh: float = 0.25,
        min_area_ratio: float = 0.0005
    ) -> List[Detection]:
        """
        Executes detection on a shelf ROI image.
        Detections with conf >= conf are confident detections.
        Detections with uncertain_thresh <= conf < conf are tagged uncertain=True.
        """
        results: List[Detection] = []

        if self.model is not None:
            # Ultralytics inference
            preds = self.model(roi_image, conf=uncertain_thresh, verbose=False)[0]
            boxes = preds.boxes
            img_h, img_w = roi_image.shape[:2]

            for box in boxes:
                c_idx = int(box.cls[0].item())
                confidence = float(box.conf[0].item())
                cls_name = CLASS_NAMES.get(c_idx, f"unknown_{c_idx}")
                sku_id = CLASS_TO_SKU.get(cls_name)

                # Normalized coordinates (x1, y1, x2, y2)
                xyxy = box.xyxy[0].cpu().numpy()
                norm_bbox = (
                    float(xyxy[0] / img_w),
                    float(xyxy[1] / img_h),
                    float(xyxy[2] / img_w),
                    float(xyxy[3] / img_h)
                )

                # Filter min area
                w_norm = norm_bbox[2] - norm_bbox[0]
                h_norm = norm_bbox[3] - norm_bbox[1]
                if (w_norm * h_norm) < min_area_ratio:
                    continue

                is_uncertain = confidence < conf
                results.append(Detection(
                    cls=cls_name,
                    sku_id=sku_id,
                    bbox=norm_bbox,
                    conf=confidence,
                    uncertain=is_uncertain,
                    model_version=self.model_version
                ))

            # Apply NMS
            results = apply_nms(results, iou_threshold=settings.iou_nms)

        return results


# Global singleton detector instance
_default_detector: Optional[ShelfDetector] = None


def get_detector(weights_path: Optional[str] = None) -> ShelfDetector:
    global _default_detector
    if _default_detector is None or weights_path is not None:
        _default_detector = ShelfDetector(weights_path=weights_path)
    return _default_detector


def detect(roi_image: np.ndarray, conf: float = settings.conf_threshold) -> List[Detection]:
    """Top-level functional interface conforming to Section 9.2."""
    detector = get_detector()
    return detector.detect(roi_image=roi_image, conf=conf)
