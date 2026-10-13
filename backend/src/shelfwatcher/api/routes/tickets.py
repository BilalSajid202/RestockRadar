from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.shelfwatcher.db.session import get_db
from src.shelfwatcher.db.models import RestockTicket, Approval, SKU, Supplier
from src.shelfwatcher import clock

router = APIRouter(prefix="/tickets", tags=["Restock Tickets"])


class ApprovalDecision(BaseModel):
    decision: str  # APPROVED or REJECTED
    note: Optional[str] = "Approved via Dashboard"
    edited_qty: Optional[int] = None


@router.get("")
def list_tickets(status: Optional[str] = None, db: Session = Depends(get_db)):
    """Lists restock tickets, optionally filtered by status."""
    query = db.query(RestockTicket, SKU, Supplier).join(
        SKU, RestockTicket.sku_id == SKU.sku_id
    ).join(
        Supplier, RestockTicket.supplier_id == Supplier.supplier_id
    )

    if status:
        query = query.filter(RestockTicket.status == status)

    tickets = query.order_by(desc(RestockTicket.ticket_id)).limit(50).all()

    return [
        {
            "ticket_id": t.ticket_id,
            "sku_id": t.sku_id,
            "sku_name": sku.name_en,
            "sku_name_ur": sku.name_ur,
            "supplier_name": sup.name,
            "qty": t.qty,
            "cost": float(t.cost),
            "status": t.status,
            "approval_required": t.approval_required,
            "created_at": t.created_at.isoformat(),
            "reasoning": t.reasoning
        }
        for t, sku, sup in tickets
    ]


@router.post("/{ticket_id}/approve")
def approve_ticket(ticket_id: int, body: ApprovalDecision = Body(...), db: Session = Depends(get_db)):
    """Approve a pending restock ticket."""
    ticket = db.query(RestockTicket).filter(RestockTicket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail=f"Ticket status is {ticket.status}, expected PENDING_APPROVAL")

    ticket.status = "APPROVED"
    if body.edited_qty is not None:
        ticket.qty = body.edited_qty

    approval = Approval(
        ticket_id=ticket_id,
        decision="APPROVED",
        decided_at=clock.now(),
        note=body.note,
        edited_qty=body.edited_qty
    )
    db.add(approval)
    db.commit()

    return {"ok": True, "ticket_id": ticket_id, "status": "APPROVED"}


@router.post("/{ticket_id}/reject")
def reject_ticket(ticket_id: int, body: ApprovalDecision = Body(...), db: Session = Depends(get_db)):
    """Reject a pending restock ticket."""
    ticket = db.query(RestockTicket).filter(RestockTicket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.status = "REJECTED"
    approval = Approval(
        ticket_id=ticket_id,
        decision="REJECTED",
        decided_at=clock.now(),
        note=body.note
    )
    db.add(approval)
    db.commit()

    return {"ok": True, "ticket_id": ticket_id, "status": "REJECTED"}
