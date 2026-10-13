from typing import Tuple, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.shelfwatcher.config import settings
from src.shelfwatcher import clock
from src.shelfwatcher.db.models import RestockTicket, Supplier


class GuardViolationError(Exception):
    """Raised when an autonomous agent guardrail is violated."""
    pass


def check_kill_switch() -> None:
    """
    Enforces Section 11 & 15 kill switch:
    If settings.agent_enabled=false, all side-effect tools return blocked.
    """
    if not settings.agent_enabled:
        raise GuardViolationError("Kill switch is ACTIVE: Agent actions are globally disabled.")


def check_daily_caps(new_cost: float, store_id: int, db: Session) -> None:
    """
    Enforces spending and volume caps per store per day:
      - MAX_AUTO_ORDERS_PER_DAY
      - MAX_AUTO_SPEND_PER_DAY
    """
    today_start = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Check order count cap
    daily_orders_count = db.query(func.count(RestockTicket.ticket_id)).filter(
        RestockTicket.store_id == store_id,
        RestockTicket.created_at >= today_start,
        RestockTicket.created_by == "agent"
    ).scalar() or 0

    if daily_orders_count >= settings.max_auto_orders_per_day:
        raise GuardViolationError(
            f"Daily automated orders cap reached ({daily_orders_count}/{settings.max_auto_orders_per_day})."
        )

    # 2. Check daily auto spend cap
    daily_spend = db.query(func.coalesce(func.sum(RestockTicket.cost), 0.0)).filter(
        RestockTicket.store_id == store_id,
        RestockTicket.created_at >= today_start,
        RestockTicket.created_by == "agent"
    ).scalar() or 0.0

    if float(daily_spend) + new_cost > settings.max_auto_spend_per_day:
        raise GuardViolationError(
            f"Daily automated spend cap exceeded: current PKR {float(daily_spend):.2f} + new PKR {new_cost:.2f} > limit PKR {settings.max_auto_spend_per_day:.2f}."
        )


def check_supplier_allowlist(supplier_email: str, db: Session) -> bool:
    """
    Ensures outbound emails can only ever be addressed to verified suppliers registered in the database.
    """
    registered = db.query(Supplier).filter(
        Supplier.email == supplier_email
    ).first()
    if not registered:
        raise GuardViolationError(f"Email '{supplier_email}' is not in the verified supplier allow-list.")
    return True
