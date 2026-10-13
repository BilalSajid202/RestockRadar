from typing import Optional, Dict, Any, Set
from datetime import datetime
from sqlalchemy.orm import Session

from src.shelfwatcher.db.models import RestockTicket, AgentLog
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher import clock


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state machine transition is attempted."""
    pass


FINAL_STATES: Set[str] = {"VERIFIED_FILLED", "REJECTED", "CANCELLED", "ESCALATED"}

VALID_TRANSITIONS: Dict[str, Set[str]] = {
    "DRAFT": {"APPROVED", "PENDING_APPROVAL", "CANCELLED"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED", "ESCALATED", "CANCELLED"},
    "APPROVED": {"ORDERED", "FAILED_SEND", "CANCELLED"},
    "FAILED_SEND": {"ORDERED", "ESCALATED", "CANCELLED"},
    "ORDERED": {"AWAITING_DELIVERY", "DELIVERED", "VERIFIED_FILLED", "NOT_FILLED", "CANCELLED"},
    "AWAITING_DELIVERY": {"DELIVERED", "VERIFIED_FILLED", "NOT_FILLED", "CANCELLED"},
    "DELIVERED": {"VERIFIED_FILLED", "NOT_FILLED", "CANCELLED"},
    "NOT_FILLED": {"ESCALATED", "VERIFIED_FILLED", "CANCELLED"},
}


class TicketStateMachine:
    """
    State machine implementing context.md Section 12 for RestockTicket.
    Enforces atomic transitions, prevents illegal state changes, and records
    append-only audit entries in agent_logs.
    """

    @staticmethod
    def can_transition(current_status: str, target_status: str) -> bool:
        if current_status in FINAL_STATES:
            return False
        allowed = VALID_TRANSITIONS.get(current_status, set())
        return target_status in allowed

    @staticmethod
    def transition(
        ticket: RestockTicket,
        new_status: str,
        actor: str,
        reason: Optional[str] = None,
        db: Optional[Session] = None
    ) -> RestockTicket:
        """
        Executes a transition on the given ticket.
        Raises InvalidStateTransitionError if illegal.
        Persists transition and writes audit log to agent_logs.
        """
        old_status = ticket.status

        if old_status == new_status:
            return ticket

        if not TicketStateMachine.can_transition(old_status, new_status):
            err_msg = (
                f"Illegal state transition from '{old_status}' to '{new_status}' attempted by actor '{actor}'."
            )
            raise InvalidStateTransitionError(err_msg)

        now = clock.now()
        ticket.status = new_status
        ticket.updated_at = now

        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            # Audit in append-only agent_logs
            summary = reason or f"Ticket status changed from {old_status} to {new_status} by {actor}."
            log = AgentLog(
                ticket_id=ticket.ticket_id,
                tool=f"transition_to_{new_status.lower()}",
                arguments={
                    "old_status": old_status,
                    "new_status": new_status,
                    "actor": actor,
                    "reason": reason
                },
                result={
                    "ticket_id": ticket.ticket_id,
                    "previous_status": old_status,
                    "current_status": new_status,
                    "success": True
                },
                reasoning_summary=summary,
                ts=now
            )
            db.add(log)
            db.commit()
            db.refresh(ticket)
            return ticket
        finally:
            if close_session:
                db.close()
