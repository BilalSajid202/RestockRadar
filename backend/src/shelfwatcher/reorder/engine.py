import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from src.shelfwatcher.db.models import (
    SKU, Shelf, Planogram, Supplier, SKUSupplier, ShelfSnapshot,
    RestockTicket, Approval, AgentLog, Event
)
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.config import settings
from src.shelfwatcher import clock
from src.shelfwatcher.forecasting.predict import predict, Forecast
from src.shelfwatcher.reorder.formulas import (
    compute_lead_time_demand,
    compute_safety_stock,
    compute_reorder_point,
    is_stockout_trigger_active,
    compute_order_quantity,
    is_approval_required
)


OPEN_TICKET_STATUSES = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "ORDERED", "AWAITING_DELIVERY"}


@dataclass
class OrderProposal:
    sku_id: int
    store_id: int
    shelf_id: int
    supplier_id: int
    qty: int
    cost: float
    approval_required: bool
    is_internal_refill: bool
    idempotency_key: str
    reasoning: Dict[str, Any]
    decision_summary: str


class ReorderEngine:
    """
    Coordinates inventory tracking, forecast consumption, reorder triggering,
    MOQ & pack constraints, capacity clamping, and duplicate ticket blocking.
    """

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def _get_session(self) -> Session:
        return self._db if self._db is not None else SessionLocal()

    def has_open_ticket(self, sku_id: int, store_id: int, db: Session) -> bool:
        """
        Guarantees Section 9.6 rule: Never create an order if an open ticket exists
        for the same SKU and store.
        """
        open_ticket = db.query(RestockTicket).filter(
            RestockTicket.sku_id == sku_id,
            RestockTicket.store_id == store_id,
            RestockTicket.status.in_(OPEN_TICKET_STATUSES)
        ).first()
        return open_ticket is not None

    def evaluate_sku(
        self,
        sku_id: int,
        store_id: int = 1,
        as_of: Optional[datetime] = None,
        db: Optional[Session] = None
    ) -> Optional[OrderProposal]:
        """
        Evaluates reorder necessity for a given SKU.
        Returns OrderProposal if reorder or internal refill is needed, else None.
        """
        close_session = False
        if db is None:
            db = self._get_session()
            close_session = (self._db is None)

        try:
            now = as_of or clock.now()

            # 1. Check for active open ticket
            if self.has_open_ticket(sku_id, store_id, db):
                return None

            # 2. Retrieve SKU & Planogram metadata
            sku = db.query(SKU).filter(SKU.sku_id == sku_id).first()
            if not sku:
                return None

            planogram_entry = db.query(Planogram).filter(Planogram.sku_id == sku_id).first()
            if not planogram_entry:
                return None

            shelf = db.query(Shelf).filter(Shelf.shelf_id == planogram_entry.shelf_id).first()
            if not shelf:
                return None

            # 3. Retrieve preferred Supplier info
            sku_supplier = db.query(SKUSupplier).filter(
                SKUSupplier.sku_id == sku_id
            ).order_by(SKUSupplier.priority.asc()).first()

            supplier = db.query(Supplier).filter(
                Supplier.supplier_id == sku_supplier.supplier_id
            ).first() if sku_supplier else db.query(Supplier).first()

            if not supplier:
                return None

            lead_time_days = float(supplier.lead_time_days)
            moq = supplier.moq or 1
            unit_price = float(sku_supplier.price) if sku_supplier and sku_supplier.price else float(sku.unit_price or 100.0)
            pack_size = sku.pack_size or 1

            # 4. Determine current inventory state
            latest_snap = db.query(ShelfSnapshot).filter(
                ShelfSnapshot.shelf_id == shelf.shelf_id,
                ShelfSnapshot.sku_id == sku_id
            ).order_by(desc(ShelfSnapshot.snapshot_id)).first()

            # Fallback to latest shelf snapshot if SKU-specific snapshot is absent
            if not latest_snap:
                latest_snap = db.query(ShelfSnapshot).filter(
                    ShelfSnapshot.shelf_id == shelf.shelf_id
                ).order_by(desc(ShelfSnapshot.snapshot_id)).first()

            shelf_units = latest_snap.item_count if latest_snap else 0
            backroom_units = shelf.backroom_units or 0
            shelf_capacity = planogram_entry.facings * planogram_entry.depth_capacity
            backroom_capacity = 100  # Default backroom allocation capacity

            # Open order units already in flight
            open_orders_sum = db.query(func.coalesce(func.sum(RestockTicket.qty), 0)).filter(
                RestockTicket.sku_id == sku_id,
                RestockTicket.store_id == store_id,
                RestockTicket.status.in_(["ORDERED", "AWAITING_DELIVERY"])
            ).scalar()
            open_order_units = int(open_orders_sum or 0)

            # 5. Check if internal backroom refill satisfies shelf shortage
            needed_on_shelf = max(0, shelf_capacity - shelf_units)
            if backroom_units > 0 and backroom_units >= needed_on_shelf and needed_on_shelf > 0:
                idempotency_key = f"refill_{sku_id}_{now.strftime('%Y%m%d')}_{shelf.shelf_id}"
                reasoning = {
                    "sku_id": sku_id,
                    "sku_name": sku.name_en,
                    "shelf_id": shelf.shelf_id,
                    "shelf_units": shelf_units,
                    "shelf_capacity": shelf_capacity,
                    "needed_on_shelf": needed_on_shelf,
                    "backroom_units": backroom_units,
                    "action": "INTERNAL_REFILL",
                    "reason": f"Backroom stock ({backroom_units}) covers shelf deficit ({needed_on_shelf}). Supplier order bypassed."
                }
                return OrderProposal(
                    sku_id=sku_id,
                    store_id=store_id,
                    shelf_id=shelf.shelf_id,
                    supplier_id=supplier.supplier_id,
                    qty=needed_on_shelf,
                    cost=0.0,
                    approval_required=False,
                    is_internal_refill=True,
                    idempotency_key=idempotency_key,
                    reasoning=reasoning,
                    decision_summary="Create internal shelf refill task for floor staff."
                )

            # 6. Retrieve forecast & evaluate stockout trigger
            fc: Forecast = predict(sku_id=sku_id, as_of=now, db=db)
            lead_time_demand = compute_lead_time_demand(fc.p50, lead_time_days)
            safety_stock = compute_safety_stock(fc.p10, fc.p90, lead_time_days, settings.service_level)
            reorder_point = compute_reorder_point(lead_time_demand, safety_stock)

            trigger_active = is_stockout_trigger_active(
                predicted_stockout_at=fc.predicted_stockout_at,
                now=now,
                lead_time_days=lead_time_days,
                buffer_hours=settings.buffer_hours
            )

            total_on_hand = shelf_units + backroom_units + open_order_units
            below_rop = total_on_hand <= reorder_point

            if not (trigger_active or below_rop):
                # No replenishment trigger met
                return None

            # 7. Calculate Order Quantity with MOQ, pack size, and capacity constraints
            final_qty, breakdown = compute_order_quantity(
                target_cover_days=settings.target_cover_days,
                daily_p50=fc.p50,
                safety_stock=safety_stock,
                shelf_units=shelf_units,
                backroom_units=backroom_units,
                open_order_units=open_order_units,
                moq=moq,
                pack_size=pack_size,
                shelf_capacity=shelf_capacity,
                backroom_capacity=backroom_capacity
            )

            if final_qty <= 0:
                return None

            # 8. Check Approval Limit Requirements
            approval_req, total_cost, limit_reason = is_approval_required(
                order_qty=final_qty,
                unit_price=unit_price,
                approval_limit_value=settings.approval_limit_value,
                approval_limit_qty=settings.approval_limit_qty
            )

            idempotency_key = f"order_{sku_id}_{now.strftime('%Y%m%d')}_{supplier.supplier_id}"

            reasoning = {
                "sku_id": sku_id,
                "sku_name": sku.name_en,
                "store_id": store_id,
                "shelf_id": shelf.shelf_id,
                "supplier_id": supplier.supplier_id,
                "supplier_name": supplier.name,
                "lead_time_days": lead_time_days,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "total_on_hand": total_on_hand,
                "trigger_active": trigger_active,
                "predicted_stockout_at": fc.predicted_stockout_at.isoformat() if fc.predicted_stockout_at else None,
                "formula_breakdown": breakdown,
                "unit_price": unit_price,
                "final_qty": final_qty,
                "total_cost": total_cost,
                "approval_required": approval_req,
                "approval_reason": limit_reason
            }

            summary = (
                f"Reorder {final_qty} units of '{sku.name_en}' from {supplier.name} at PKR {total_cost:.2f}. "
                f"{'Approval required: ' + limit_reason if approval_req else 'Automated order ready.'}"
            )

            return OrderProposal(
                sku_id=sku_id,
                store_id=store_id,
                shelf_id=shelf.shelf_id,
                supplier_id=supplier.supplier_id,
                qty=final_qty,
                cost=total_cost,
                approval_required=approval_req,
                is_internal_refill=False,
                idempotency_key=idempotency_key,
                reasoning=reasoning,
                decision_summary=summary
            )

        finally:
            if close_session:
                db.close()

    def create_ticket_from_proposal(
        self,
        proposal: OrderProposal,
        created_by: str = "agent",
        db: Optional[Session] = None
    ) -> RestockTicket:
        """
        Idempotently persists the RestockTicket and initial Approval record if over limit.
        Logs action to agent_logs.
        """
        close_session = False
        if db is None:
            db = self._get_session()
            close_session = (self._db is None)

        try:
            # Check for existing ticket with idempotency key
            existing = db.query(RestockTicket).filter(
                RestockTicket.idempotency_key == proposal.idempotency_key
            ).first()
            if existing:
                return existing

            now = clock.now()
            # Initial status: DRAFT if cost <= limit, else PENDING_APPROVAL
            initial_status = "PENDING_APPROVAL" if proposal.approval_required else "APPROVED"

            ticket = RestockTicket(
                store_id=proposal.store_id,
                sku_id=proposal.sku_id,
                shelf_id=proposal.shelf_id,
                supplier_id=proposal.supplier_id,
                qty=proposal.qty,
                cost=proposal.cost,
                status=initial_status,
                approval_required=proposal.approval_required,
                idempotency_key=proposal.idempotency_key,
                reasoning=proposal.reasoning,
                created_by=created_by,
                created_at=now,
                updated_at=now
            )
            db.add(ticket)
            db.flush()

            # If approval required, create pending approval record
            if proposal.approval_required:
                appr = Approval(
                    ticket_id=ticket.ticket_id,
                    requested_at=now,
                    note=proposal.reasoning.get("approval_reason", "Exceeds automated approval limit.")
                )
                db.add(appr)

            # Log to append-only agent_logs
            log = AgentLog(
                ticket_id=ticket.ticket_id,
                tool="create_restock_ticket",
                arguments={
                    "sku_id": proposal.sku_id,
                    "shelf_id": proposal.shelf_id,
                    "qty": proposal.qty,
                    "supplier_id": proposal.supplier_id
                },
                result={
                    "ticket_id": ticket.ticket_id,
                    "status": ticket.status,
                    "approval_required": ticket.approval_required,
                    "cost": float(ticket.cost)
                },
                reasoning_summary=proposal.decision_summary,
                ts=now
            )
            db.add(log)
            db.commit()
            db.refresh(ticket)
            return ticket

        finally:
            if close_session:
                db.close()

    def evaluate_all_skus(
        self,
        store_id: int = 1,
        as_of: Optional[datetime] = None
    ) -> List[OrderProposal]:
        """
        Scans all SKUs in the planogram and produces proposals for items needing restock.
        """
        db = self._get_session()
        try:
            skus = db.query(SKU).all()
            proposals = []
            for sku in skus:
                prop = self.evaluate_sku(sku.sku_id, store_id=store_id, as_of=as_of, db=db)
                if prop:
                    proposals.append(prop)
            return proposals
        finally:
            if self._db is None:
                db.close()
