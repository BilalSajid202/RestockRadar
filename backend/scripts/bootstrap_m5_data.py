import os
import sys
from datetime import datetime, timezone
import pandas as pd

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shelfwatcher.simulation.demand_sim import DemandSimulator, SKU_DEMAND_PROFILES
from src.shelfwatcher.simulation.shelf_sim import ShelfDemandSimulator
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.db.models import DemandSeries


def bootstrap_milestone_5():
    print("=" * 60)
    print(" Milestone 5: Bootstrapping 6+ Months Demand History & Replay")
    print("=" * 60)

    # 1. Generate 200 days (> 6 months) daily history for all 10 SKUs
    sim = DemandSimulator(seed=42)
    end_date = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
    target_days = 200

    print(f"[*] Generating {target_days} days of demand history for {len(SKU_DEMAND_PROFILES)} SKUs...")
    records = sim.generate_daily_series(store_id=1, days=target_days, end_date=end_date)

    # Save to CSV
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sim_dir = os.path.join(backend_dir, "data", "sim")
    os.makedirs(sim_dir, exist_ok=True)
    csv_path = os.path.join(sim_dir, "demand_history.csv")
    df = pd.DataFrame(records)
    df.to_csv(csv_path, index=False)
    print(f"[OK] Exported {len(records)} records to {csv_path}")

    # 2. Populate PostgreSQL demand_series
    print("[*] Upserting records into PostgreSQL 'demand_series' table...")
    db = SessionLocal()
    try:
        inserted = sim.populate_database(records, db=db)
        total_in_db = db.query(DemandSeries).filter(DemandSeries.store_id == 1).count()
        print(f"[OK] Inserted/merged {inserted} records. Total in demand_series: {total_in_db}")
    finally:
        db.close()

    # 3. Generate matching replay sequence in data/replay/
    print("\n[*] Generating matching visual replay sequence in data/replay/ (Shelf-Demand Link)...")
    replay_dir = os.path.join(backend_dir, "data", "replay")
    shelf_sim = ShelfDemandSimulator(replay_dir=replay_dir)
    replay_paths = shelf_sim.generate_replay_sequence(
        start_time=datetime(2026, 10, 8, 8, 0, 0, tzinfo=timezone.utc),
        hours=48,
        interval_hours=3,
        auto_delivery_at_hour=36
    )
    print(f"[OK] Generated {len(replay_paths)} timestamped replay frames showing depletion and refill.")

    print("\n" + "=" * 60)
    print("[SUCCESS] Milestone 5 acceptance criteria achieved:")
    print(f"  - Daily history: {target_days} days (>= 180 days target) for {len(SKU_DEMAND_PROFILES)} SKUs")
    print(f"  - Total records: {len(records)}")
    print(f"  - Replay sequence: {len(replay_paths)} matching frames in data/replay/")
    print("=" * 60)


if __name__ == "__main__":
    bootstrap_milestone_5()
