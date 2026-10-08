from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Numeric, Text, JSON, PrimaryKeyConstraint
)
from sqlalchemy.orm import relationship
from src.shelfwatcher.db.session import Base


def utcnow():
    return datetime.now(timezone.utc)


class Store(Base):
    __tablename__ = "stores"

    store_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    timezone = Column(String(100), default="UTC")
    default_language = Column(String(10), default="en")

    cameras = relationship("Camera", back_populates="store")
    users = relationship("User", back_populates="store")


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.store_id"), nullable=True)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), nullable=False)  # Admin, Manager, Procurement, Floor Staff, ML Engineer, Read-only
    language = Column(String(10), default="en")
    password_hash = Column(String(255), nullable=False)
    twofa_secret = Column(String(255), nullable=True)

    store = relationship("Store", back_populates="users")


class Camera(Base):
    __tablename__ = "cameras"

    camera_id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.store_id"), nullable=False)
    name = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)  # phone, rtsp, replay, upload
    url_enc = Column(Text, nullable=True)
    status = Column(String(50), default="ACTIVE")
    last_seen = Column(DateTime(timezone=True), nullable=True)

    store = relationship("Store", back_populates="cameras")
    shelves = relationship("Shelf", back_populates="camera")
    frames = relationship("Frame", back_populates="camera")


class Shelf(Base):
    __tablename__ = "shelves"

    shelf_id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.camera_id"), nullable=False)
    name = Column(String(255), nullable=False)
    aisle = Column(String(100), nullable=True)
    level = Column(String(50), nullable=True)
    roi_polygon = Column(JSON, nullable=True)  # List of [x, y] coordinates
    total_facings = Column(Integer, default=10)
    backroom_units = Column(Integer, default=0)
    depth_factor = Column(Numeric(5, 2), default=1.0)

    camera = relationship("Camera", back_populates="shelves")
    planograms = relationship("Planogram", back_populates="shelf")
    snapshots = relationship("ShelfSnapshot", back_populates="shelf")
    events = relationship("Event", back_populates="shelf")


class SKU(Base):
    __tablename__ = "skus"

    sku_id = Column(Integer, primary_key=True, autoincrement=True)
    name_en = Column(String(255), nullable=False)
    name_ur = Column(String(255), nullable=True)
    category = Column(String(100), nullable=True)
    unit_price = Column(Numeric(10, 2), nullable=False)
    pack_size = Column(Integer, default=1)
    shelf_life_days = Column(Integer, nullable=True)

    planograms = relationship("Planogram", back_populates="sku")
    suppliers = relationship("SKUSupplier", back_populates="sku")


class Planogram(Base):
    __tablename__ = "planogram"

    shelf_id = Column(Integer, ForeignKey("shelves.shelf_id"), primary_key=True)
    zone = Column(Integer, primary_key=True)
    sku_id = Column(Integer, ForeignKey("skus.sku_id"), nullable=False)
    facings = Column(Integer, default=1)
    depth_capacity = Column(Integer, default=5)

    shelf = relationship("Shelf", back_populates="planograms")
    sku = relationship("SKU", back_populates="planograms")


class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    lead_time_days = Column(Numeric(5, 2), default=1.0)
    moq = Column(Integer, default=1)

    skus = relationship("SKUSupplier", back_populates="supplier")


class SKUSupplier(Base):
    __tablename__ = "sku_suppliers"

    sku_id = Column(Integer, ForeignKey("skus.sku_id"), primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.supplier_id"), primary_key=True)
    price = Column(Numeric(10, 2), nullable=False)
    priority = Column(Integer, default=1)

    sku = relationship("SKU", back_populates="suppliers")
    supplier = relationship("Supplier", back_populates="skus")


class Frame(Base):
    __tablename__ = "frames"

    frame_id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.camera_id"), nullable=False)
    captured_at = Column(DateTime(timezone=True), default=utcnow)
    path = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=True)
    valid_flag = Column(Boolean, default=True)
    quality_score = Column(Float, nullable=True)
    source = Column(String(50), default="replay")

    camera = relationship("Camera", back_populates="frames")
    detections = relationship("Detection", back_populates="frame")


class Detection(Base):
    __tablename__ = "detections"

    detection_id = Column(Integer, primary_key=True, autoincrement=True)
    frame_id = Column(Integer, ForeignKey("frames.frame_id"), nullable=False)
    shelf_id = Column(Integer, ForeignKey("shelves.shelf_id"), nullable=True)
    detection_class = Column("class", String(100), nullable=False)
    sku_id = Column(Integer, ForeignKey("skus.sku_id"), nullable=True)
    bbox = Column(JSON, nullable=False)  # [x1, y1, x2, y2]
    confidence = Column(Float, nullable=False)
    track_id = Column(Integer, nullable=True)
    uncertain = Column(Boolean, default=False)
    model_version = Column(String(50), nullable=True)

    frame = relationship("Frame", back_populates="detections")


class ShelfSnapshot(Base):
    __tablename__ = "shelf_snapshots"

    snapshot_id = Column(Integer, primary_key=True, autoincrement=True)
    shelf_id = Column(Integer, ForeignKey("shelves.shelf_id"), nullable=False)
    sku_id = Column(Integer, ForeignKey("skus.sku_id"), nullable=True)
    captured_at = Column(DateTime(timezone=True), default=utcnow)
    item_count = Column(Integer, default=0)
    gap_count = Column(Integer, default=0)
    fill_pct = Column(Float, default=100.0)
    estimated = Column(Boolean, default=False)
    status = Column(String(20), default="OK")  # OK, LOW, EMPTY, UNKNOWN

    shelf = relationship("Shelf", back_populates="snapshots")


class Event(Base):
    __tablename__ = "events"

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    shelf_id = Column(Integer, ForeignKey("shelves.shelf_id"), nullable=False)
    sku_id = Column(Integer, ForeignKey("skus.sku_id"), nullable=True)
    type = Column(String(50), nullable=False)  # ITEM_REMOVED, ITEM_ADDED, GAP_OPENED, GAP_CLOSED, SHELF_REFILLED, MISPLACED
    track_id = Column(Integer, nullable=True)
    occurred_at = Column(DateTime(timezone=True), default=utcnow)
    meta = Column(JSON, nullable=True)

    shelf = relationship("Shelf", back_populates="events")


class DemandSeries(Base):
    __tablename__ = "demand_series"

    store_id = Column(Integer, primary_key=True)
    sku_id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    units_removed = Column(Integer, default=0)
    units_sold = Column(Integer, nullable=True)
    stockout_flag = Column(Boolean, default=False)
    promo_flag = Column(Boolean, default=False)
    price = Column(Numeric(10, 2), nullable=True)


class Forecast(Base):
    __tablename__ = "forecasts"

    forecast_id = Column(Integer, primary_key=True, autoincrement=True)
    sku_id = Column(Integer, ForeignKey("skus.sku_id"), nullable=False)
    generated_at = Column(DateTime(timezone=True), default=utcnow)
    horizon_days = Column(Integer, default=7)
    p10 = Column(JSON, nullable=False)
    p50 = Column(JSON, nullable=False)
    p90 = Column(JSON, nullable=False)
    predicted_stockout_at = Column(DateTime(timezone=True), nullable=True)
    model_version = Column(String(50), nullable=True)
    used_fallback = Column(Boolean, default=False)


class RestockTicket(Base):
    __tablename__ = "restock_tickets"

    ticket_id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, nullable=False)
    sku_id = Column(Integer, ForeignKey("skus.sku_id"), nullable=False)
    shelf_id = Column(Integer, ForeignKey("shelves.shelf_id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.supplier_id"), nullable=False)
    qty = Column(Integer, nullable=False)
    cost = Column(Numeric(12, 2), nullable=False)
    status = Column(String(50), default="DRAFT")
    approval_required = Column(Boolean, default=False)
    idempotency_key = Column(String(100), unique=True, nullable=False)
    reasoning = Column(JSON, nullable=True)
    created_by = Column(String(50), default="agent")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    approval_id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("restock_tickets.ticket_id"), nullable=False)
    requested_at = Column(DateTime(timezone=True), default=utcnow)
    decided_by = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    decision = Column(String(50), nullable=True)  # APPROVED, REJECTED
    decided_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)
    edited_qty = Column(Integer, nullable=True)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("restock_tickets.ticket_id"), nullable=True)
    tool = Column(String(100), nullable=False)
    arguments = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    reasoning_summary = Column(Text, nullable=True)
    ts = Column(DateTime(timezone=True), default=utcnow)


class Verification(Base):
    __tablename__ = "verifications"

    verification_id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("restock_tickets.ticket_id"), nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    fill_pct = Column(Float, nullable=True)
    outcome = Column(String(50), nullable=True)  # VERIFIED_FILLED, NOT_FILLED, INCONCLUSIVE
    image_path = Column(Text, nullable=True)


class OutboundEmail(Base):
    __tablename__ = "outbound_emails"

    email_id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("restock_tickets.ticket_id"), nullable=False)
    to_addr = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    sent_at = Column(DateTime(timezone=True), default=utcnow)
    status = Column(String(50), default="SENT")  # SENT, DRYRUN, FAILED
    message_id = Column(String(100), nullable=True)


class Summary(Base):
    __tablename__ = "summaries"

    summary_id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, nullable=False)
    summary_date = Column(DateTime(timezone=True), nullable=False)
    language = Column(String(10), default="en")
    text = Column(Text, nullable=False)
    facts = Column(JSON, nullable=False)
    image_refs = Column(JSON, nullable=True)


class ChatLog(Base):
    __tablename__ = "chat_logs"

    chat_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    question = Column(Text, nullable=False)
    language = Column(String(10), default="en")
    generated_sql = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    ts = Column(DateTime(timezone=True), default=utcnow)
    blocked_reason = Column(String(100), nullable=True)


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    model_id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(50), nullable=False)  # detector, forecaster
    version = Column(String(50), nullable=False)
    metrics = Column(JSON, nullable=True)
    status = Column(String(50), default="CANDIDATE")  # CHAMPION, CANDIDATE, RETIRED
    trained_at = Column(DateTime(timezone=True), default=utcnow)
    path = Column(Text, nullable=False)


class Glossary(Base):
    __tablename__ = "glossary"

    term_en = Column(String(100), primary_key=True)
    term_ur = Column(String(100), nullable=False)
    unit = Column(String(50), nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)
    scope = Column(String(50), default="global")
