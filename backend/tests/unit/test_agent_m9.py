from datetime import datetime, timezone, timedelta
import pytest

from src.shelfwatcher.config import settings
from src.shelfwatcher import clock
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.db.models import (
    RestockTicket, Approval, OutboundEmail, Verification, AgentLog,
    ShelfSnapshot, SKU, Supplier
)
from src.shelfwatcher.agent.state_machine import TicketStateMachine, InvalidStateTransitionError
from src.shelfwatcher.agent.guards import (
    check_kill_switch, check_daily_caps, check_supplier_allowlist, GuardViolationError
)
from src.shelfwatcher.agent.email_service import send_supplier_purchase_email
from src.shelfwatcher.agent.tools import (
    get_shelf_state, get_forecast, calculate_order, create_restock_ticket,
    send_supplier_email, recheck_camera, close_or_escalate_ticket
)


def clean_ticket(db, ticket_id):
    db.query(Verification).filter(Verification.ticket_id == ticket_id).delete()
    db.query(OutboundEmail).filter(OutboundEmail.ticket_id == ticket_id).delete()
    db.query(Approval).filter(Approval.ticket_id == ticket_id).delete()
    db.query(AgentLog).filter(AgentLog.ticket_id == ticket_id).delete()
    db.query(RestockTicket).filter(RestockTicket.ticket_id == ticket_id).delete()
    db.commit()


def test_scenario_s1_full_autonomous_loop():
    """
    Scenario S1: Steady demand, order under limit ->
    Ticket -> email -> next-day refill image -> VERIFIED_FILLED
    """
    db = SessionLocal()
    ticket_id = None
    try:
        now = clock.now()
        # 1. Create restock ticket under limit
        ticket = RestockTicket(
            store_id=1,
            sku_id=1,
            shelf_id=1,
            supplier_id=1,
            qty=24,
            cost=2400.0,
            status="APPROVED",  # cost <= limit
            approval_required=False,
            idempotency_key=f"test_s1_{now.timestamp()}",
            created_by="agent",
            created_at=now,
            updated_at=now
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        ticket_id = ticket.ticket_id

        # 2. Dispatch email to supplier
        res_email = send_supplier_purchase_email(ticket_id=ticket.ticket_id, db=db)
        assert res_email["ok"] is True
        assert res_email["status"] == "ORDERED"

        db.refresh(ticket)
        assert ticket.status == "ORDERED"

        # 3. Simulate high fill snapshot (refilled shelf: 95%)
        refill_snap = ShelfSnapshot(
            shelf_id=1,
            sku_id=1,
            item_count=19,
            gap_count=1,
            fill_pct=95.0,
            status="OK",
            captured_at=now + timedelta(days=1)
        )
        db.add(refill_snap)
        db.commit()

        # 4. Next-day camera recheck passes -> closes as VERIFIED_FILLED
        res_recheck = recheck_camera(shelf_id=1, ticket_id=ticket.ticket_id)
        assert res_recheck["ok"] is True
        assert res_recheck["verified"] is True
        assert res_recheck["ticket_status"] == "VERIFIED_FILLED"

        db.refresh(ticket)
        assert ticket.status == "VERIFIED_FILLED"
    finally:
        if ticket_id:
            clean_ticket(db, ticket_id)
        db.close()


def test_scenario_s2_order_above_limit_hitl_approval():
    """
    Scenario S2: Order above limit ->
    Stops at PENDING_APPROVAL; no email until approved; approve -> continues
    """
    db = SessionLocal()
    ticket_id = None
    try:
        now = clock.now()
        # Create ticket above limit (cost 30,000 > 20,000 limit)
        ticket = RestockTicket(
            store_id=1,
            sku_id=1,
            shelf_id=1,
            supplier_id=1,
            qty=300,
            cost=30000.0,
            status="PENDING_APPROVAL",
            approval_required=True,
            idempotency_key=f"test_s2_{now.timestamp()}",
            created_by="agent",
            created_at=now,
            updated_at=now
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        ticket_id = ticket.ticket_id

        # Attempt to email without approval must be BLOCKED
        email_res = send_supplier_purchase_email(ticket_id=ticket.ticket_id, db=db)
        assert email_res["ok"] is False
        assert "Unauthorized email attempt" in email_res["error"]

        db.refresh(ticket)
        assert ticket.status == "PENDING_APPROVAL"

        # Human manager approves order
        TicketStateMachine.transition(
            ticket=ticket,
            new_status="APPROVED",
            actor="user:1 (Manager)",
            reason="Approved order for weekend promo event.",
            db=db
        )

        db.refresh(ticket)
        assert ticket.status == "APPROVED"

        # Email is now permitted
        email_after = send_supplier_purchase_email(ticket_id=ticket.ticket_id, db=db)
        assert email_after["ok"] is True
        assert email_after["status"] == "ORDERED"

        db.refresh(ticket)
        assert ticket.status == "ORDERED"
    finally:
        if ticket_id:
            clean_ticket(db, ticket_id)
        db.close()


def test_scenario_s3_supplier_ordered_not_refilled_escalation():
    """
    Scenario S3: Supplier ordered but shelf not refilled ->
    NOT_FILLED -> ESCALATED
    """
    db = SessionLocal()
    ticket_id = None
    try:
        now = clock.now()
        ticket = RestockTicket(
            store_id=1,
            sku_id=1,
            shelf_id=1,
            supplier_id=1,
            qty=24,
            cost=2400.0,
            status="ORDERED",
            approval_required=False,
            idempotency_key=f"test_s3_{now.timestamp()}",
            created_by="agent",
            created_at=now,
            updated_at=now
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        ticket_id = ticket.ticket_id

        # Low fill snapshot (empty/not refilled: 30% < 85%)
        unfilled_snap = ShelfSnapshot(
            shelf_id=1,
            sku_id=1,
            item_count=3,
            gap_count=7,
            fill_pct=30.0,
            status="LOW",
            captured_at=now + timedelta(days=1)
        )
        db.add(unfilled_snap)
        db.commit()

        # Recheck detects unrefilled shelf
        res_recheck = recheck_camera(shelf_id=1, ticket_id=ticket.ticket_id)
        assert res_recheck["ok"] is True
        assert res_recheck["verified"] is False
        assert res_recheck["ticket_status"] == "ESCALATED"

        db.refresh(ticket)
        assert ticket.status == "ESCALATED"
    finally:
        if ticket_id:
            clean_ticket(db, ticket_id)
        db.close()


def test_scenario_s5_duplicate_trigger_blocking():
    """
    Scenario S5: Duplicate trigger for same SKU ->
    Only one ticket created; second trigger blocked while open ticket exists.
    """
    db = SessionLocal()
    ticket_id = None
    try:
        now = clock.now()
        # Active open ticket
        ticket = RestockTicket(
            store_id=1,
            sku_id=2,
            shelf_id=1,
            supplier_id=1,
            qty=36,
            cost=3600.0,
            status="ORDERED",
            approval_required=False,
            idempotency_key=f"test_s5_{now.timestamp()}",
            created_by="agent",
            created_at=now,
            updated_at=now
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        ticket_id = ticket.ticket_id

        # Second calculation for same SKU must report not needed / blocked
        calc = calculate_order(sku_id=2, store_id=1)
        assert calc["reorder_needed"] is False
    finally:
        if ticket_id:
            clean_ticket(db, ticket_id)
        db.close()


def test_scenario_s7_kill_switch_blocking():
    """
    Scenario S7: Kill switch on ->
    All side-effect tools return blocked; zero external modifications.
    """
    original_setting = settings.agent_enabled
    try:
        settings.agent_enabled = False

        with pytest.raises(GuardViolationError) as exc_info:
            check_kill_switch()
        assert "Kill switch is ACTIVE" in str(exc_info.value)

        # Attempting create_restock_ticket returns error
        res = create_restock_ticket(sku_id=1, shelf_id=1, qty=12, supplier_id=1)
        assert res["ok"] is False
        assert "Kill switch" in res["error"]
    finally:
        settings.agent_enabled = original_setting


def test_state_machine_illegal_transition_raises():
    db = SessionLocal()
    ticket = RestockTicket(
        store_id=1,
        sku_id=1,
        shelf_id=1,
        supplier_id=1,
        qty=10,
        cost=1000.0,
        status="DRAFT",
        approval_required=False,
        idempotency_key="test_illegal_tx",
        created_at=clock.now(),
        updated_at=clock.now()
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    try:
        # Cannot jump straight from DRAFT to VERIFIED_FILLED
        with pytest.raises(InvalidStateTransitionError):
            TicketStateMachine.transition(ticket, "VERIFIED_FILLED", actor="bad_actor", db=db)
    finally:
        clean_ticket(db, ticket.ticket_id)
        db.close()
