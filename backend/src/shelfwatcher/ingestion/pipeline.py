import os
import hashlib
from typing import Optional, Dict, Any, List
import cv2
import numpy as np

from src.shelfwatcher.ingestion.base import Frame, FrameSource, crop_roi
from src.shelfwatcher.ingestion.quality import check_quality, QualityResult
from src.shelfwatcher.ingestion.privacy import anonymize_frame
from src.shelfwatcher.vision.detector import detect, Detection
from src.shelfwatcher.vision.counting import build_snapshot, ShelfSnapshotResult
from src.shelfwatcher.db.models import Camera, Shelf, Planogram, Frame as DBFrame, Detection as DBDetection, ShelfSnapshot as DBSnapshot
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher import clock


def compute_sha256(image: np.ndarray) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_RAW_DIR = os.path.join(BACKEND_ROOT, "data", "raw")


def process_camera_frame(
    camera_id: int,
    source: FrameSource,
    output_dir: Optional[str] = None,
    db_session = None
) -> Dict[str, Any]:
    if output_dir is None:
        output_dir = DEFAULT_RAW_DIR
    elif not os.path.isabs(output_dir):
        output_dir = os.path.join(BACKEND_ROOT, output_dir)
    """
    Executes the ingestion pipeline for one camera frame according to context.md Section 7.2 & 9.1:
    1. Ingestion: fetch next frame.
    2. Quality Gate: inspect brightness, blur, uniformity.
       - If invalid: mark valid_flag=False, NO snapshot created, shelf status -> UNKNOWN.
    3. Privacy Blur: blur persons detected in frame.
    4. Store Frame: record in frames table with SHA256.
    5. For each shelf: crop ROI -> detect items & gaps -> build snapshot -> store in DB.
    """
    close_db = False
    if db_session is None:
        db = SessionLocal()
        close_db = True
    else:
        db = db_session

    try:
        # 1. Fetch frame
        frame: Optional[Frame] = source.next_frame()

        # Handle missing camera feed
        if frame is None or frame.image is None:
            # Query all shelves for this camera and mark as UNKNOWN
            shelves = db.query(Shelf).filter(Shelf.camera_id == camera_id).all()
            for sh in shelves:
                unknown_snap = DBSnapshot(
                    shelf_id=sh.shelf_id,
                    captured_at=clock.now(),
                    item_count=0,
                    gap_count=sh.total_facings,
                    fill_pct=0.0,
                    estimated=False,
                    status="UNKNOWN"
                )
                db.add(unknown_snap)
            db.commit()
            return {
                "ok": False,
                "error": "No frame available from source",
                "shelf_status": "UNKNOWN"
            }

        # 2. Quality evaluation
        quality: QualityResult = check_quality(frame.image)
        os.makedirs(output_dir, exist_ok=True)
        img_sha = compute_sha256(frame.image)
        timestamp_str = frame.captured_at.strftime("%Y%m%d_%H%M%S")
        saved_path = os.path.join(output_dir, f"cam{camera_id}_{timestamp_str}_{img_sha[:8]}.jpg")

        if not quality.valid_flag:
            # Save raw invalid frame
            cv2.imwrite(saved_path, frame.image)
            db_frame = DBFrame(
                camera_id=camera_id,
                captured_at=frame.captured_at,
                path=saved_path,
                sha256=img_sha,
                valid_flag=False,
                quality_score=quality.quality_score,
                source=frame.source
            )
            db.add(db_frame)

            # Rule: Invalid frames create NO snapshot; shelf status becomes UNKNOWN
            shelves = db.query(Shelf).filter(Shelf.camera_id == camera_id).all()
            for sh in shelves:
                unknown_snap = DBSnapshot(
                    shelf_id=sh.shelf_id,
                    captured_at=frame.captured_at,
                    item_count=0,
                    gap_count=sh.total_facings,
                    fill_pct=0.0,
                    estimated=False,
                    status="UNKNOWN"
                )
                db.add(unknown_snap)

            db.commit()
            return {
                "ok": False,
                "valid_flag": False,
                "quality_score": quality.quality_score,
                "reason": quality.failure_reason,
                "shelf_status": "UNKNOWN"
            }

        # 3. Privacy blur (class person)
        initial_detections = detect(frame.image, conf=0.30)
        person_detections = [d for d in initial_detections if d.cls == "person"]
        anonymized_img = anonymize_frame(frame.image, person_detections)

        # 4. Save anonymized image & DB frame
        cv2.imwrite(saved_path, anonymized_img)
        db_frame = DBFrame(
            camera_id=camera_id,
            captured_at=frame.captured_at,
            path=saved_path,
            sha256=img_sha,
            valid_flag=True,
            quality_score=quality.quality_score,
            source=frame.source
        )
        db.add(db_frame)
        db.flush()

        # 5. Process shelves for this camera
        shelves = db.query(Shelf).filter(Shelf.camera_id == camera_id).all()
        processed_shelves = []

        for sh in shelves:
            roi_img = crop_roi(anonymized_img, sh.roi_polygon)
            roi_dets: List[Detection] = detect(roi_img)
            planograms = db.query(Planogram).filter(Planogram.shelf_id == sh.shelf_id).all()

            # Record detections
            for d in roi_dets:
                db_det = DBDetection(
                    frame_id=db_frame.frame_id,
                    shelf_id=sh.shelf_id,
                    detection_class=d.cls,
                    sku_id=d.sku_id,
                    bbox=list(d.bbox),
                    confidence=d.conf,
                    uncertain=d.uncertain,
                    model_version=d.model_version
                )
                db.add(db_det)

            # Build shelf snapshot
            snap_res: ShelfSnapshotResult = build_snapshot(sh, roi_dets, planograms)
            db_snap = DBSnapshot(
                shelf_id=sh.shelf_id,
                captured_at=snap_res.captured_at,
                item_count=snap_res.item_count,
                gap_count=snap_res.gap_count,
                fill_pct=snap_res.fill_pct,
                estimated=snap_res.estimated,
                status=snap_res.status
            )
            db.add(db_snap)
            processed_shelves.append({
                "shelf_id": sh.shelf_id,
                "fill_pct": snap_res.fill_pct,
                "status": snap_res.status,
                "item_count": snap_res.item_count,
                "gap_count": snap_res.gap_count
            })

        db.commit()
        return {
            "ok": True,
            "valid_flag": True,
            "quality_score": quality.quality_score,
            "shelves": processed_shelves
        }

    except Exception as e:
        db.rollback()
        raise e
    finally:
        if close_db:
            db.close()
