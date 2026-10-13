import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.shelfwatcher.db.models import (
    Shelf, ShelfSnapshot, SKU, Supplier, SKUSupplier, Planogram,
    RestockTicket, Approval, Verification, AgentLog, Frame
)
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.config import settings
from src.shelfwatcher import clock
from src.shelfwatcher.forecasting.predict import predict
from src.shelfwatcher.reorder.engine import ReorderEngine, OrderProposal
from src.shelfwatcher.agent.guards import check_kill_switch, check_daily_caps
from src.shelfwatcher.agent.state_machine import TicketStateMachine
from src.shelfwatcher.agent.email_service import send_supplier_purchase_email


def log_agent_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    result: Dict[str, Any],
    summary: str,
    ticket_id: Optional[int] = None,
    db: Optional[Session] = None
) -> None:
    """Appends tool invocation record into immutable agent_logs table."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        log_entry = AgentLog(
            ticket_id=ticket_id,
            tool=tool_name,
            arguments=args,
            result=result,
            reasoning_summary=summary,
            ts=clock.now()
        )
        db.add(log_entry)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        if close_db:
            db.close()


def get_shelf_state(shelf_id: int) -> Dict[str, Any]:
    """Retrieves current camera counts, gaps, fill %, status, and latest image path."""
    db = SessionLocal()
    try:
        shelf = db.query(Shelf).filter(Shelf.shelf_id == shelf_id).first()
        if not shelf:
            return {"ok": False, "error": f"Shelf {shelf_id} not found."}

        snap = db.query(ShelfSnapshot).filter(
            ShelfSnapshot.shelf_id == shelf_id
        ).order_by(desc(ShelfSnapshot.snapshot_id)).first()

        latest_frame = db.query(Frame).filter(
            Frame.camera_id == shelf.camera_id,
            Frame.valid_flag.is_(True)
        ).order_by(desc(Frame.frame_id)).first()

        res = {
            "ok": True,
            "shelf_id": shelf_id,
            "shelf_name": shelf.name,
            "item_count": snap.item_count if snap else 0,
            "gap_count": snap.gap_count if snap else 0,
            "fill_pct": snap.fill_pct if snap else 100.0,
            "status": snap.status if snap else "UNKNOWN",
            "backroom_units": shelf.backroom_units or 0,
            "image_path": latest_frame.path if latest_frame else None,
            "captured_at": snap.captured_at.isoformat() if snap and snap.captured_at else None
        }
        log_agent_tool_call("get_shelf_state", {"shelf_id": shelf_id}, res, f"Fetched state for shelf {shelf_id}", db=db)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def get_forecast(sku_id: int) -> Dict[str, Any]:
    """Retrieves 7-day multi-quantile demand forecast and stockout projection for a SKU."""
    db = SessionLocal()
    try:
        fc = predict(sku_id=sku_id, db=db)
        res = {
            "ok": True,
            "sku_id": sku_id,
            "horizon_days": fc.horizon_days,
            "p10": fc.p10,
            "p50": fc.p50,
            "p90": fc.p90,
            "predicted_stockout_at": fc.predicted_stockout_at.isoformat() if fc.predicted_stockout_at else None,
            "model_version": fc.model_version,
            "used_fallback": fc.used_fallback
        }
        log_agent_tool_call("get_forecast", {"sku_id": sku_id}, res, f"Computed forecast for SKU {sku_id}", db=db)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def get_supplier_info(sku_id: int) -> Dict[str, Any]:
    """Retrieves preferred supplier details, MOQ, pack size, price, and lead time for a SKU."""
    db = SessionLocal()
    try:
        sku = db.query(SKU).filter(SKU.sku_id == sku_id).first()
        if not sku:
            return {"ok": False, "error": f"SKU {sku_id} not found."}

        sku_sup = db.query(SKUSupplier).filter(
            SKUSupplier.sku_id == sku_id
        ).order_by(SKUSupplier.priority.asc()).first()

        supplier = db.query(Supplier).filter(
            Supplier.supplier_id == sku_sup.supplier_id
        ).first() if sku_sup else db.query(Supplier).first()

        if not supplier:
            return {"ok": False, "error": "No supplier registered for SKU."}

        res = {
            "ok": True,
            "sku_id": sku_id,
            "sku_name": sku.name_en,
            "supplier_id": supplier.supplier_id,
            "supplier_name": supplier.name,
            "supplier_email": supplier.email,
            "lead_time_days": float(supplier.lead_time_days),
            "moq": supplier.moq or 1,
            "pack_size": sku.pack_size or 1,
            "unit_price": float(sku_sup.price) if sku_sup and sku_sup.price else float(sku.unit_price or 100.0)
        }
        log_agent_tool_call("get_supplier_info", {"sku_id": sku_id}, res, f"Retrieved supplier info for SKU {sku_id}", db=db)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def calculate_order(sku_id: int, store_id: int = 1) -> Dict[str, Any]:
    """Evaluates reorder need, applies replenishment formulas, and calculates cost and limits."""
    db = SessionLocal()
    try:
        engine = ReorderEngine(db=db)
        proposal = engine.evaluate_sku(sku_id=sku_id, store_id=store_id, db=db)

        if not proposal:
            res = {"ok": True, "reorder_needed": False, "message": "No order or refill needed at this time."}
            log_agent_tool_call("calculate_order", {"sku_id": sku_id}, res, "Evaluated reorder: not needed", db=db)
            return res

        res = {
            "ok": True,
            "reorder_needed": True,
            "sku_id": proposal.sku_id,
            "shelf_id": proposal.shelf_id,
            "supplier_id": proposal.supplier_id,
            "qty": proposal.qty,
            "cost": proposal.cost,
            "approval_required": proposal.approval_required,
            "is_internal_refill": proposal.is_internal_refill,
            "idempotency_key": proposal.idempotency_key,
            "reasoning": proposal.reasoning,
            "decision_summary": proposal.decision_summary
        }
        log_agent_tool_call("calculate_order", {"sku_id": sku_id}, res, proposal.decision_summary, db=db)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def create_restock_ticket(
    sku_id: int,
    shelf_id: int,
    qty: int,
    supplier_id: int,
    reasoning: Optional[Dict[str, Any]] = None,
    store_id: int = 1
) -> Dict[str, Any]:
    """Idempotently generates restock ticket and creates pending approval record if required."""
    db = SessionLocal()
    try:
        check_kill_switch()

        sku = db.query(SKU).filter(SKU.sku_id == sku_id).first()
        unit_price = float(sku.unit_price or 100.0) if sku else 100.0
        cost = round(qty * unit_price, 2)

        # Enforce daily spending and orders caps
        check_daily_caps(cost, store_id, db)

        # Re-check approval limit
        approval_req = (cost > settings.approval_limit_value) or (qty > settings.approval_limit_qty)
        now = clock.now()
        idempotency_key = f"tkt_{sku_id}_{now.strftime('%Y%m%d')}_{supplier_id}"

        engine = ReorderEngine(db=db)
        proposal = OrderProposal(
            sku_id=sku_id,
            store_id=store_id,
            shelf_id=shelf_id,
            supplier_id=supplier_id,
            qty=qty,
            cost=cost,
            approval_required=approval_req,
            is_internal_refill=False,
            idempotency_key=idempotency_key,
            reasoning=reasoning or {"manual": True},
            decision_summary=f"Created order ticket for SKU {sku_id}"
        )

        ticket = engine.create_ticket_from_proposal(proposal, created_by="agent", db=db)
        res = {
            "ok": True,
            "ticket_id": ticket.ticket_id,
            "status": ticket.status,
            "approval_required": ticket.approval_required,
            "cost": float(ticket.cost),
            "qty": ticket.qty
        }
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def request_approval(ticket_id: int) -> Dict[str, Any]:
    """Generates an explicit approval request for an order exceeding configured limits."""
    db = SessionLocal()
    try:
        ticket = db.query(RestockTicket).filter(RestockTicket.ticket_id == ticket_id).first()
        if not ticket:
            return {"ok": False, "error": f"Ticket {ticket_id} not found."}

        appr = db.query(Approval).filter(Approval.ticket_id == ticket_id).first()
        if not appr:
            appr = Approval(
                ticket_id=ticket.ticket_id,
                requested_at=clock.now(),
                note=f"High-value restock PKR {float(ticket.cost):.2f} requires human sign-off."
            )
            db.add(appr)
            db.commit()

        res = {
            "ok": True,
            "approval_id": appr.approval_id,
            "ticket_id": ticket_id,
            "cost": float(ticket.cost),
            "status": ticket.status,
            "message": "Approval request notified to manager."
        }
        log_agent_tool_call("request_approval", {"ticket_id": ticket_id}, res, "Approval requested", ticket_id=ticket_id, db=db)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def send_supplier_email(ticket_id: int) -> Dict[str, Any]:
    """Dispatches purchase order email to supplier. Enforces approval status and allowlists."""
    return send_supplier_purchase_email(ticket_id=ticket_id)


def schedule_recheck(
    ticket_id: int,
    shelf_id: int,
    run_at: Optional[str] = None
) -> Dict[str, Any]:
    """Schedules next-day camera verification capture."""
    db = SessionLocal()
    try:
        now = clock.now()
        sched_time = datetime.fromisoformat(run_at) if run_at else (now + timedelta(days=1, hours=2))

        verif = Verification(
            ticket_id=ticket_id,
            scheduled_at=sched_time,
            outcome="SCHEDULED"
        )
        db.add(verif)
        db.commit()

        res = {
            "ok": True,
            "verification_id": verif.verification_id,
            "ticket_id": ticket_id,
            "scheduled_at": sched_time.isoformat()
        }
        log_agent_tool_call("schedule_recheck", {"ticket_id": ticket_id, "shelf_id": shelf_id}, res, "Verification scheduled", ticket_id=ticket_id, db=db)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def recheck_camera(shelf_id: int, ticket_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Executes next-day shelf refill verification.
    Passes if fill_pct >= FILL_TARGET (default 85%).
    Transitions ticket to VERIFIED_FILLED if passed, or NOT_FILLED -> ESCALATED if failed.
    """
    db = SessionLocal()
    try:
        shelf = db.query(Shelf).filter(Shelf.shelf_id == shelf_id).first()
        if not shelf:
            return {"ok": False, "error": f"Shelf {shelf_id} not found."}

        snap = db.query(ShelfSnapshot).filter(
            ShelfSnapshot.shelf_id == shelf_id
        ).order_by(desc(ShelfSnapshot.snapshot_id)).first()

        fill_pct = snap.fill_pct if snap else 0.0
        passed = fill_pct >= settings.fill_target

        res = {
            "ok": True,
            "shelf_id": shelf_id,
            "fill_pct": fill_pct,
            "target_fill_pct": settings.fill_target,
            "verified": passed
        }

        if ticket_id is not None:
            ticket = db.query(RestockTicket).filter(RestockTicket.ticket_id == ticket_id).first()
            if ticket:
                verif = db.query(Verification).filter(Verification.ticket_id == ticket_id).order_by(desc(Verification.verification_id)).first()
                if not verif:
                    verif = Verification(ticket_id=ticket_id, scheduled_at=clock.now())
                    db.add(verif)

                verif.executed_at = clock.now()
                verif.fill_pct = fill_pct

                if passed:
                    verif.outcome = "VERIFIED_FILLED"
                    TicketStateMachine.transition(
                        ticket,
                        new_status="VERIFIED_FILLED",
                        actor="agent:recheck_camera",
                        reason=f"Refill verified: fill {fill_pct:.1f}% >= target {settings.fill_target:.1f}%.",
                        db=db
                    )
                else:
                    verif.outcome = "NOT_FILLED"
                    # Transition to NOT_FILLED then ESCALATED per state machine
                    TicketStateMachine.transition(
                        ticket,
                        new_status="NOT_FILLED",
                        actor="agent:recheck_camera",
                        reason=f"Refill failed: fill {fill_pct:.1f}% < target {settings.fill_target:.1f}%.",
                        db=db
                    )
                    TicketStateMachine.transition(
                        ticket,
                        new_status="ESCALATED",
                        actor="system:escalation",
                        reason="Shelf restock recheck failed after delivery window.",
                        db=db
                    )
                res["ticket_status"] = ticket.status

        log_agent_tool_call("recheck_camera", {"shelf_id": shelf_id, "ticket_id": ticket_id}, res, "Camera recheck executed", ticket_id=ticket_id, db=db)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def close_or_escalate_ticket(ticket_id: int, outcome: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Closes ticket as VERIFIED_FILLED or escalates to management."""
    db = SessionLocal()
    try:
        ticket = db.query(RestockTicket).filter(RestockTicket.ticket_id == ticket_id).first()
        if not ticket:
            return {"ok": False, "error": f"Ticket {ticket_id} not found."}

        target_status = "VERIFIED_FILLED" if outcome.upper() in {"VERIFIED", "VERIFIED_FILLED"} else "ESCALATED"
        TicketStateMachine.transition(
            ticket,
            new_status=target_status,
            actor="agent:manual_resolution",
            reason=reason or f"Ticket marked {target_status} by tool.",
            db=db
        )
        return {"ok": True, "ticket_id": ticket_id, "new_status": target_status}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
