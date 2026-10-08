from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Environment & System Clock
    sim_now: Optional[str] = None
    default_language: str = "en"

    # Database & Celery Broker (PostgreSQL native)
    database_url: str = "postgresql://postgres:postgres@localhost:5432/shelfwatcher"
    broker_url: str = "sqla+postgresql://postgres:postgres@localhost:5432/shelfwatcher"

    # Vision & Ingestion
    capture_interval_min: int = 15
    conf_threshold: float = 0.40
    iou_nms: float = 0.50
    n_consistent: int = 2
    miss_tolerance_frames: int = 3
    putback_window_min: int = 5
    refill_delta: float = 30.0

    # Forecasting & Inventory Reorder
    service_level: float = 0.95
    buffer_hours: int = 12
    target_cover_days: int = 7
    approval_limit_value: float = 20000.0  # PKR
    approval_limit_qty: int = 200
    max_auto_orders_per_day: int = 10
    max_auto_spend_per_day: float = 50000.0
    fill_target: float = 85.0
    recheck_time: str = "10:00"
    summary_time: str = "08:00"

    # Safety Controls & Flags
    agent_enabled: bool = True
    dry_run: bool = True

    # Generative AI & Chatbot
    llm_provider: str = "mock"
    llm_model: str = "mock-model"
    llm_api_key: Optional[str] = None

    # SMTP Configuration
    smtp_host: str = "localhost"
    smtp_port: int = 8025
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    from_addr: str = "procurement@restockradar.local"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
