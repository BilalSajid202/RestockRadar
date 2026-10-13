from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Optional, List, Tuple
import numpy as np
import cv2


@dataclass
class Frame:
    camera_id: int
    captured_at: datetime  # UTC, from clock.now()
    image: np.ndarray      # BGR uint8
    source: str            # "phone" | "rtsp" | "replay" | "upload"
    filename: Optional[str] = None


class FrameSource(Protocol):
    def next_frame(self) -> Optional[Frame]:
        """Returns the next available frame, or None if no frame is available."""
        ...


def crop_roi(image: np.ndarray, roi_polygon: Optional[List[List[int]]]) -> np.ndarray:
    """
    Crops the Region of Interest (ROI) from a frame given a polygon [[x, y], ...].
    If no polygon or fewer than 3 vertices are provided, returns the whole frame.
    """
    if image is None or image.size == 0:
        return image

    if not roi_polygon or len(roi_polygon) < 3:
        return image

    pts = np.array(roi_polygon, dtype=np.int32)

    # Calculate bounding rectangle of the polygon
    x, y, w, h = cv2.boundingRect(pts)
    x = max(0, x)
    y = max(0, y)
    w = min(w, image.shape[1] - x)
    h = min(h, image.shape[0] - y)

    if w <= 0 or h <= 0:
        return image

    cropped = image[y:y + h, x:x + w]
    return cropped
