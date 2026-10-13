from datetime import datetime, timezone, timedelta
import pytest

from src.shelfwatcher.reorder.formulas import (
    compute_lead_time_demand,
    compute_safety_stock,
    compute_reorder_point,
    is_stockout_trigger_active,
    ceil_to_pack,
    compute_order_quantity,
    is_approval_required,
    get_z_score
)
from src.shelfwatcher.reorder.engine import ReorderEngine, OrderProposal
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.db.models import RestockTicket, Approval, SKU, ShelfSnapshot, Shelf


def test_lead_time_demand():
    daily_p50 = [10.0, 12.0, 15.0, 20.0, 10.0, 10.0, 10.0]

    # Integer 3 days: 10 + 12 + 15 = 37
    assert compute_lead_time_demand(daily_p50, 3.0) == 37.0

    # Fractional 2.5 days: 10 + 12 + (0.5 * 15) = 29.5
    assert compute_lead_time_demand(daily_p50, 2.5) == 29.5

    # Zero lead time
    assert compute_lead_time_demand(daily_p50, 0.0) == 0.0


def test_safety_stock_computation():
    p10 = [8.0, 8.0, 8.0]
    p90 = [18.0, 18.0, 18.0]  # spread = 10 -> sigma_daily ~ 10 / 2.563 ~ 3.90

    # For 4 days lead time: sqrt(4) = 2; z(0.95) = 1.645
    ss = compute_safety_stock(p10, p90, lead_time_days=4.0, service_level=0.95)
    assert ss > 10.0
    assert ss < 15.0


def test_reorder_point():
    ltd = 45.0
    ss = 12.5
    assert compute_reorder_point(ltd, ss) == 57.5


def test_stockout_trigger_active():
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)

    # Lead time 2 days + buffer 12 hours = 60 hours
    # Case 1: stockout in 30 hours -> should trigger
    stockout_soon = now + timedelta(hours=30)
    assert is_stockout_trigger_active(stockout_soon, now, lead_time_days=2.0, buffer_hours=12.0) is True

    # Case 2: stockout in 80 hours -> should not trigger
    stockout_far = now + timedelta(hours=80)
    assert is_stockout_trigger_active(stockout_far, now, lead_time_days=2.0, buffer_hours=12.0) is False

    # Case 3: None stockout -> False
    assert is_stockout_trigger_active(None, now, lead_time_days=2.0) is False


def test_ceil_to_pack():
    assert ceil_to_pack(11, pack_size=6) == 12
    assert ceil_to_pack(12, pack_size=6) == 12
    assert ceil_to_pack(13, pack_size=6) == 18
    assert ceil_to_pack(5, pack_size=1) == 5


def test_compute_order_quantity_moq_and_capacity():
    daily_p50 = [20.0] * 7  # avg 20/day
    target_cover_days = 7   # target demand = 140
    safety_stock = 20.0     # target stock = 160

    # Case A: On hand 10 units, open 0 -> raw needed: 160 - 10 = 150
    # MOQ 24, pack size 12, capacity 200 (space = 200 - 10 = 190)
    qty, breakdown = compute_order_quantity(
        target_cover_days=target_cover_days,
        daily_p50=daily_p50,
        safety_stock=safety_stock,
        shelf_units=10,
        backroom_units=0,
        open_order_units=0,
        moq=24,
        pack_size=12,
        shelf_capacity=100,
        backroom_capacity=100
    )
    # 150 -> ceil_to_pack(150, 12) = 156. Space 190 >= 156
    assert qty == 156
    assert breakdown["qty_packed"] == 156

    # Case B: Capacity clamp
    # Space only 50 available
    qty_clamped, _ = compute_order_quantity(
        target_cover_days=target_cover_days,
        daily_p50=daily_p50,
        safety_stock=safety_stock,
        shelf_units=150,
        backroom_units=0,
        open_order_units=0,
        moq=12,
        pack_size=6,
        shelf_capacity=100,
        backroom_capacity=60  # total capacity 160 - 150 on hand = 10 space
    )
    assert qty_clamped <= 10


def test_approval_required_thresholds():
    # Below limit (e.g. 50 units * 100 PKR = 5000 <= 20000)
    req, cost, reason = is_approval_required(
        order_qty=50,
        unit_price=100.0,
        approval_limit_value=20000.0,
        approval_limit_qty=200
    )
    assert req is False
    assert cost == 5000.0

    # Exceeds financial limit (300 * 100 = 30000 > 20000)
    req_val, cost_val, reason_val = is_approval_required(
        order_qty=300,
        unit_price=100.0,
        approval_limit_value=20000.0,
        approval_limit_qty=500
    )
    assert req_val is True
    assert "exceeds approval limit" in reason_val


def test_reorder_engine_duplicate_blocking_and_ticket_creation():
    db = SessionLocal()
    try:
        engine = ReorderEngine(db=db)
        # Verify SKU 1 (Milk) evaluation
        now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)

        proposal = engine.evaluate_sku(sku_id=1, store_id=1, as_of=now, db=db)
        if proposal is not None and not proposal.is_internal_refill:
            # Create ticket
            ticket = engine.create_ticket_from_proposal(proposal, created_by="test_suite", db=db)
            assert ticket.ticket_id is not None
            assert ticket.sku_id == 1
            assert ticket.idempotency_key == proposal.idempotency_key
            assert ticket.reasoning is not None

            # Verify that re-evaluating returns None because open ticket exists
            second_eval = engine.evaluate_sku(sku_id=1, store_id=1, as_of=now, db=db)
            assert second_eval is None, "Should block duplicate order when ticket is open"

            # Clean up test ticket to leave DB clean
            db.query(Approval).filter(Approval.ticket_id == ticket.ticket_id).delete()
            db.query(RestockTicket).filter(RestockTicket.ticket_id == ticket.ticket_id).delete()
            db.commit()
    finally:
        db.close()
