from typing import Optional
import cv2

from src.shelfwatcher.ingestion.base import Frame, FrameSource
from src.shelfwatcher import clock


class PhoneCameraSource(FrameSource):
    """
    Ingests live or simulated frames from an RTSP stream or HTTP MJPEG feed (IP Webcam / DroidCam).
    """

    def __init__(self, stream_url: str, camera_id: int = 1):
        self.stream_url = stream_url
        self.camera_id = camera_id
        self._cap: Optional[cv2.VideoCapture] = None

    def _get_capture(self) -> cv2.VideoCapture:
        if self._cap is None or not self._cap.isOpened():
            self._cap = cv2.VideoCapture(self.stream_url)
        return self._cap

    def next_frame(self) -> Optional[Frame]:
        cap = self._get_capture()
        if not cap.isOpened():
            return None

        ret, frame_bgr = cap.read()
        if not ret or frame_bgr is None:
            return None

        return Frame(
            camera_id=self.camera_id,
            captured_at=clock.now(),
            image=frame_bgr,
            source="phone" if "rtsp" not in self.stream_url.lower() else "rtsp"
        )

    def close(self):
        if self._cap is not None and self._cap.isOpened():
            self._cap.release()
            self._cap = None
