import math
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any


def get_z_score(service_level: float = 0.95) -> float:
    """
    Returns standard normal z-score for a given service level cycle service level.
    Standard common points:
      0.90 -> 1.282
      0.95 -> 1.645
      0.98 -> 2.054
      0.99 -> 2.326
    """
    if service_level >= 0.99:
        return 2.326
    elif service_level >= 0.98:
        return 2.054
    elif service_level >= 0.95:
        return 1.645
    elif service_level >= 0.90:
        return 1.282
    elif service_level >= 0.85:
        return 1.036
    elif service_level >= 0.80:
        return 0.842
    return 1.645


def compute_lead_time_demand(daily_p50: List[float], lead_time_days: float) -> float:
    """
    Computes expected demand over supplier lead time using forecast P50.
    Handles integer or fractional lead time days.
    """
    if not daily_p50 or lead_time_days <= 0:
        return 0.0

    full_days = int(lead_time_days)
    frac_day = lead_time_days - full_days

    # Sum up to available horizon
    days_to_sum = min(full_days, len(daily_p50))
    total_ltd = sum(daily_p50[:days_to_sum])

    # If lead time exceeds horizon, extrapolate with average daily demand
    avg_daily = sum(daily_p50) / len(daily_p50)
    if full_days > len(daily_p50):
        total_ltd += (full_days - len(daily_p50)) * avg_daily

    if frac_day > 0:
        next_day_demand = daily_p50[days_to_sum] if days_to_sum < len(daily_p50) else avg_daily
        total_ltd += frac_day * next_day_demand

    return round(float(total_ltd), 2)


def compute_safety_stock(
    p10: List[float],
    p90: List[float],
    lead_time_days: float,
    service_level: float = 0.95,
    min_sigma: float = 1.0
) -> float:
    """
    Computes safety stock = z(service_level) * sigma_leadtime.
    sigma_daily is derived from the forecast inter-quantile spread:
    (P90 - P10) ~ 2.563 * sigma under Gaussian demand.
    sigma_leadtime = sigma_daily * sqrt(lead_time_days).
    """
    if lead_time_days <= 0:
        return 0.0

    z = get_z_score(service_level)

    # Estimate daily standard deviation from quantiles
    if p10 and p90 and len(p10) == len(p90) and len(p10) > 0:
        spreads = [max(0.0, p90[i] - p10[i]) for i in range(len(p10))]
        avg_spread = sum(spreads) / len(spreads)
        sigma_daily = max(min_sigma, avg_spread / 2.563)
    else:
        sigma_daily = min_sigma

    sigma_leadtime = sigma_daily * math.sqrt(lead_time_days)
    safety_stock = z * sigma_leadtime
    return round(float(max(0.0, safety_stock)), 2)


def compute_reorder_point(lead_time_demand: float, safety_stock: float) -> float:
    """
    reorder_point = lead_time_demand + safety_stock
    """
    return round(float(lead_time_demand + safety_stock), 2)


def is_stockout_trigger_active(
    predicted_stockout_at: Optional[datetime],
    now: datetime,
    lead_time_days: float,
    buffer_hours: float = 12.0
) -> bool:
    """
    Trigger condition from Section 9.6:
    trigger = predicted_stockout_at - now <= lead_time_days + BUFFER_HOURS
    """
    if predicted_stockout_at is None:
        return False

    trigger_horizon = timedelta(days=lead_time_days, hours=buffer_hours)
    time_to_stockout = predicted_stockout_at - now

    return time_to_stockout <= trigger_horizon


def ceil_to_pack(qty: int, pack_size: int) -> int:
    """
    Rounds up quantity to nearest pack/case size.
    """
    if pack_size <= 1:
        return max(0, qty)
    return math.ceil(max(0, qty) / pack_size) * pack_size


def compute_order_quantity(
    target_cover_days: int,
    daily_p50: List[float],
    safety_stock: float,
    shelf_units: int,
    backroom_units: int,
    open_order_units: int,
    moq: int,
    pack_size: int,
    shelf_capacity: int,
    backroom_capacity: int
) -> Tuple[int, Dict[str, Any]]:
    """
    Computes required order quantity strictly conforming to Section 9.6:
    1. order_qty_raw = target_cover_days * daily_p50 + safety_stock - (shelf_units + backroom_units + open_order_units)
    2. order_qty     = ceil_to_pack(max(order_qty_raw, MOQ))
    3. order_qty     = min(order_qty, shelf_capacity + backroom_capacity - on_hand)
    """
    avg_daily_p50 = (sum(daily_p50) / len(daily_p50)) if daily_p50 else 0.0
    target_stock = (target_cover_days * avg_daily_p50) + safety_stock
    current_inventory = shelf_units + backroom_units + open_order_units

    order_qty_raw = target_stock - current_inventory

    if order_qty_raw <= 0:
        return 0, {
            "order_qty_raw": round(order_qty_raw, 2),
            "target_stock": round(target_stock, 2),
            "current_inventory": current_inventory,
            "reason": "Current inventory plus open orders covers target stock."
        }

    # Apply MOQ and case pack sizing
    qty_after_moq = max(int(math.ceil(order_qty_raw)), moq)
    qty_packed = ceil_to_pack(qty_after_moq, pack_size)

    # Capacity constraint clamp
    total_capacity = shelf_capacity + backroom_capacity
    on_hand = shelf_units + backroom_units
    max_available_space = max(0, total_capacity - on_hand)
    final_qty = min(qty_packed, max_available_space)

    breakdown = {
        "avg_daily_p50": round(avg_daily_p50, 2),
        "target_stock": round(target_stock, 2),
        "current_inventory": current_inventory,
        "order_qty_raw": round(order_qty_raw, 2),
        "moq": moq,
        "pack_size": pack_size,
        "qty_after_moq": qty_after_moq,
        "qty_packed": qty_packed,
        "total_capacity": total_capacity,
        "max_available_space": max_available_space,
        "final_qty": final_qty
    }
    return final_qty, breakdown


def is_approval_required(
    order_qty: int,
    unit_price: float,
    approval_limit_value: float,
    approval_limit_qty: int
) -> Tuple[bool, float, str]:
    """
    Checks if order exceeds financial or unit quantity limits (Section 9.6 & 15).
    """
    cost = round(order_qty * unit_price, 2)
    reasons = []
    if cost > approval_limit_value:
        reasons.append(f"Cost PKR {cost:.2f} exceeds approval limit PKR {approval_limit_value:.2f}")
    if order_qty > approval_limit_qty:
        reasons.append(f"Quantity {order_qty} exceeds limit {approval_limit_qty}")

    req = len(reasons) > 0
    reason_str = "; ".join(reasons) if req else "Within automated limits"
    return req, cost, reason_str
