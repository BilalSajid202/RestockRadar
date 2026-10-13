from typing import Dict, Any, List
from src.shelfwatcher.tasks.celery_app import celery_app
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.db.models import Camera
from src.shelfwatcher.ingestion.replay import ReplaySource
from src.shelfwatcher.ingestion.phone import PhoneCameraSource
from src.shelfwatcher.ingestion.pipeline import process_camera_frame


@celery_app.task(name="src.shelfwatcher.tasks.schedules.capture_all_cameras_task")
def capture_all_cameras_task() -> Dict[str, Any]:
    """
    Periodic job triggered by Celery Beat every CAPTURE_INTERVAL_MIN (default 15m)
    to ingest frames, evaluate quality, and record shelf snapshots (context.md Section 7.2).
    """
    db = SessionLocal()
    results: List[Dict[str, Any]] = []

    try:
        active_cameras = db.query(Camera).filter(Camera.status == "ACTIVE").all()

        for cam in active_cameras:
            # Select frame source according to camera configuration
            if cam.source_type == "phone" or cam.source_type == "rtsp":
                source = PhoneCameraSource(stream_url=cam.url_enc or "", camera_id=cam.camera_id)
            else:
                # Default to replay source
                source = ReplaySource(folder_path="data/replay", camera_id=cam.camera_id, loop=True)

            res = process_camera_frame(
                camera_id=cam.camera_id,
                source=source,
                output_dir="data/raw",
                db_session=db
            )
            results.append({
                "camera_id": cam.camera_id,
                "camera_name": cam.name,
                "result": res
            })

        return {
            "status": "success",
            "processed_count": len(results),
            "cameras": results
        }

    finally:
        db.close()
