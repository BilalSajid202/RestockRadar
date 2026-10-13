from datetime import datetime, timezone, timedelta
import pytest

from src.shelfwatcher.simulation.demand_sim import DemandSimulator, SKU_DEMAND_PROFILES
from src.shelfwatcher.simulation.shelf_sim import ShelfDemandSimulator
from src.shelfwatcher.simulation.scenario_runner import ScenarioRunner
from src.shelfwatcher import clock


def test_demand_simulator_records():
    sim = DemandSimulator(seed=100)
    end_date = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
    records = sim.generate_daily_series(store_id=1, days=180, end_date=end_date)

    # 180 days * 10 SKUs = 1800 records
    assert len(records) == 180 * 10
    sku_ids = {r["sku_id"] for r in records}
    assert sku_ids == set(range(1, 11))

    for r in records:
        assert r["units_removed"] >= 0
        assert r["price"] > 0
        assert isinstance(r["stockout_flag"], bool)
        assert isinstance(r["promo_flag"], bool)


def test_holiday_multiplier():
    sim = DemandSimulator(seed=100)
    # Eid-ul-Fitr (May 2)
    dt_eid = datetime(2026, 5, 2, 0, 0, 0, tzinfo=timezone.utc)
    is_hol, mult, name = sim.is_holiday(dt_eid)
    assert is_hol is True
    assert mult > 1.0
    assert "Eid" in name


def test_shelf_demand_depletion_and_replenishment():
    shelf_sim = ShelfDemandSimulator(shelf_capacity_per_sku=10)

    # Initially 100% full (10 units * 10 SKUs = 100 units)
    initial_units = sum(shelf_sim.inventory.values())
    assert initial_units == 100

    # Apply 20 units demand across SKUs
    hourly_demand = {1: 3, 2: 2, 5: 5}
    fill_pct = shelf_sim.apply_hourly_demand(hourly_demand)
    assert fill_pct == 90.0
    assert shelf_sim.inventory[1] == 7
    assert shelf_sim.inventory[2] == 8
    assert shelf_sim.inventory[5] == 5

    # Replenish SKU 1
    new_fill = shelf_sim.deliver_replenishment(sku_id=1, qty=3)
    assert shelf_sim.inventory[1] == 10
    assert new_fill == 93.0


def test_scenario_runner_clock():
    runner = ScenarioRunner(camera_id=1)
    t0 = datetime(2026, 10, 8, 14, 0, 0, tzinfo=timezone.utc)
    runner.set_time(t0)

    assert clock.now() == t0
    t1 = runner.advance_time(delta_minutes=30)
    assert t1 == t0 + timedelta(minutes=30)
    assert clock.now() == t1

    # Reset clock
    clock.set_sim_time(None)
