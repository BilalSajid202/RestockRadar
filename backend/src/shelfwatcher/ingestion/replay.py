import os
import glob
from datetime import datetime, timezone
from typing import Optional, List
import cv2

from src.shelfwatcher.ingestion.base import Frame, FrameSource
from src.shelfwatcher import clock


class ReplaySource(FrameSource):
    """
    Simulates a camera feed by serving timestamped images from a local folder.
    Timestamps are parsed from filename 'YYYYMMDD_HHMMSS.jpg' or generated via clock.now().
    """

    def __init__(self, folder_path: str, camera_id: int = 1, loop: bool = True):
        self.folder_path = folder_path
        self.camera_id = camera_id
        self.loop = loop
        self.current_index = 0
        self.image_files: List[str] = []
        self._refresh_files()

    def _refresh_files(self):
        if not os.path.exists(self.folder_path):
            self.image_files = []
            return

        patterns = [
            os.path.join(self.folder_path, "*.jpg"),
            os.path.join(self.folder_path, "*.jpeg"),
            os.path.join(self.folder_path, "*.png")
        ]
        files = []
        for pat in patterns:
            files.extend(glob.glob(pat))
        self.image_files = sorted(files)

    def next_frame(self) -> Optional[Frame]:
        if not self.image_files:
            self._refresh_files()
            if not self.image_files:
                return None

        if self.current_index >= len(self.image_files):
            if self.loop:
                self.current_index = 0
            else:
                return None

        filepath = self.image_files[self.current_index]
        self.current_index += 1

        img = cv2.imread(filepath)
        if img is None:
            return None

        filename = os.path.basename(filepath)
        captured_at = self._parse_timestamp(filename)

        return Frame(
            camera_id=self.camera_id,
            captured_at=captured_at,
            image=img,
            source="replay",
            filename=filename
        )

    def _parse_timestamp(self, filename: str) -> datetime:
        """Parses YYYYMMDD_HHMMSS from filename, or falls back to clock.now()."""
        stem = os.path.splitext(filename)[0]
        # Look for 15-char timestamp pattern like 20261008_120000
        parts = stem.split("_")
        for part in parts:
            if len(part) == 15 and part[8] == "T":
                try:
                    return datetime.strptime(part, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
        if len(parts) >= 2:
            try:
                candidate = f"{parts[0]}_{parts[1]}"
                return datetime.strptime(candidate, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        return clock.now()
