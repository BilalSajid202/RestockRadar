from celery import Celery
from src.shelfwatcher.config import settings

# Celery application configured with PostgreSQL/SQLAlchemy broker (Section 6)
celery_app = Celery(
    "shelfwatcher",
    broker=settings.broker_url,
    backend="db+" + settings.database_url if not settings.broker_url.startswith("redis") else None,
    include=["src.shelfwatcher.tasks.schedules"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "capture-cameras-every-interval": {
            "task": "src.shelfwatcher.tasks.schedules.capture_all_cameras_task",
            "schedule": float(settings.capture_interval_min * 60),  # In seconds
        },
    }
)
