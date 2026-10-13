from typing import Optional, Union
import numpy as np
import cv2

from src.shelfwatcher.ingestion.base import Frame, FrameSource
from src.shelfwatcher import clock


class UploadSource(FrameSource):
    """
    Ingests manually uploaded frames via API or file input.
    """

    def __init__(self, camera_id: int = 1):
        self.camera_id = camera_id
        self._staged_frame: Optional[Frame] = None

    def stage_bytes(self, image_bytes: bytes, filename: Optional[str] = None):
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is not None:
            self._staged_frame = Frame(
                camera_id=self.camera_id,
                captured_at=clock.now(),
                image=img,
                source="upload",
                filename=filename
            )

    def stage_image(self, image_bgr: np.ndarray, filename: Optional[str] = None):
        if image_bgr is not None:
            self._staged_frame = Frame(
                camera_id=self.camera_id,
                captured_at=clock.now(),
                image=image_bgr,
                source="upload",
                filename=filename
            )

    def next_frame(self) -> Optional[Frame]:
        frame = self._staged_frame
        self._staged_frame = None
        return frame
