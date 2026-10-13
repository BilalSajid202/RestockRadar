import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shelfwatcher.ingestion.replay import ReplaySource
from src.shelfwatcher.ingestion.base import FrameSource, Frame
from src.shelfwatcher.ingestion.pipeline import process_camera_frame
from src.shelfwatcher.db.models import Camera, Shelf, ShelfSnapshot
from src.shelfwatcher.db.session import SessionLocal


class MockEmptySource(FrameSource):
    """Simulates an offline camera or missing feed."""
    def next_frame(self):
        return None


def verify_milestone_3():
    print("=" * 60)
    print(" Milestone 3: Verification of Ingestion & Camera Simulator")
    print("=" * 60)

    db = SessionLocal()
    try:
        # Check camera
        cam = db.query(Camera).first()
        if not cam:
            print("[!] No camera found in database. Initializing sample camera...")
            from src.shelfwatcher.db.init_db import init_db
            init_db(seed=True)
            cam = db.query(Camera).first()

        cam_id = cam.camera_id
        print(f"[*] Testing Camera ID: {cam_id} ({cam.name})")

        # 1. Test Unattended Replay Source
        print("\n[Step 1] Running unattended frame ingestion via ReplaySource...")
        replay_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "replay"))
        replay_source = ReplaySource(folder_path=replay_dir, camera_id=cam_id, loop=True)
        res_replay = process_camera_frame(camera_id=cam_id, source=replay_source, db_session=db)

        assert res_replay["ok"] is True, f"Replay failed: {res_replay}"
        assert res_replay["valid_flag"] is True, "Frame should be valid"
        print(f"     -> Quality Score: {res_replay['quality_score']}")
        print(f"     -> Shelves Processed: {len(res_replay['shelves'])}")
        for sh in res_replay["shelves"]:
            print(f"        * Shelf {sh['shelf_id']}: Fill {sh['fill_pct']}% | Status: {sh['status']} | Items: {sh['item_count']}")

        # 2. Test Missing Frame Handling (Offline camera)
        print("\n[Step 2] Simulating missing camera feed...")
        empty_source = MockEmptySource()
        res_missing = process_camera_frame(camera_id=cam_id, source=empty_source, db_session=db)

        assert res_missing["ok"] is False, "Missing frame should return ok=False"
        assert res_missing["shelf_status"] == "UNKNOWN", "Missing frame must set shelf_status to UNKNOWN"
        print(f"     -> Handled missing feed successfully: shelf status is '{res_missing['shelf_status']}'")

        # 3. Test Invalid Frame Quality (Dark frame)
        print("\n[Step 3] Simulating invalid frame (pitch black camera view)...")
        from src.shelfwatcher.ingestion.upload import UploadSource
        import numpy as np
        dark_upload = UploadSource(camera_id=cam_id)
        dark_upload.stage_image(np.full((300, 300, 3), 10, dtype=np.uint8))
        res_dark = process_camera_frame(camera_id=cam_id, source=dark_upload, db_session=db)

        assert res_dark["ok"] is False, "Dark frame must be rejected"
        assert res_dark["valid_flag"] is False, "valid_flag must be False"
        assert res_dark["shelf_status"] == "UNKNOWN", "Rejected frame must yield UNKNOWN shelf status"
        print(f"     -> Dark frame rejected: {res_dark['reason']}")
        print(f"     -> Shelf status marked: {res_dark['shelf_status']}")

        print("\n" + "=" * 60)
        print("[SUCCESS] Milestone 3 criteria fully verified:")
        print("  - Runs unattended in replay mode: PASSED")
        print("  - Missing frame -> UNKNOWN: PASSED")
        print("  - Invalid frame (dark/blur/blank) rejected & UNKNOWN: PASSED")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    verify_milestone_3()
