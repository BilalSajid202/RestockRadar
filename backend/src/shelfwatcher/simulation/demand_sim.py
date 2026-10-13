import os
import random
import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
from sqlalchemy.orm import Session

from src.shelfwatcher.db.models import DemandSeries, SKU
from src.shelfwatcher.db.session import SessionLocal


# 10 SKUs with base daily demand rates and pricing
SKU_DEMAND_PROFILES: Dict[int, Dict] = {
    1: {"name": "Milk 1L", "base_rate": 30.0, "category": "Dairy", "price": 280.0, "volatility": 0.25},
    2: {"name": "Yogurt 500g", "base_rate": 18.0, "category": "Dairy", "price": 180.0, "volatility": 0.30},
    3: {"name": "Apple Juice 1L", "base_rate": 14.0, "category": "Beverages", "price": 320.0, "volatility": 0.35},
    4: {"name": "Orange Juice 1L", "base_rate": 12.0, "category": "Beverages", "price": 320.0, "volatility": 0.35},
    5: {"name": "White Bread 400g", "base_rate": 35.0, "category": "Bakery", "price": 140.0, "volatility": 0.20},
    6: {"name": "Corn Flakes 375g", "base_rate": 8.0, "category": "Breakfast", "price": 650.0, "volatility": 0.40},
    7: {"name": "Cooking Oil 1L", "base_rate": 16.0, "category": "Pantry", "price": 520.0, "volatility": 0.25},
    8: {"name": "Basmati Rice 1kg", "base_rate": 22.0, "category": "Pantry", "price": 380.0, "volatility": 0.25},
    9: {"name": "Tomato Ketchup 500g", "base_rate": 9.0, "category": "Condiments", "price": 290.0, "volatility": 0.35},
    10: {"name": "Black Tea 400g", "base_rate": 15.0, "category": "Beverages", "price": 750.0, "volatility": 0.30},
}


class DemandSimulator:
    """
    Synthesizes realistic retail demand series incorporating:
    - Day-of-week seasonality (Friday-Sunday peaks)
    - Monthly salary/payday surge (1st-5th of the month)
    - Religious/public holiday surges (Ramadan, Eid, National holidays)
    - Promotional discounts (price reduction + demand uplift)
    - Censored demand / Stockout periods
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def is_holiday(self, dt: datetime) -> Tuple[bool, float, str]:
        """Returns (is_holiday, demand_multiplier, holiday_name)."""
        month, day = dt.month, dt.day

        # Pakistan public/religious holiday calendar approximations
        if month == 3 and day == 23:
            return True, 1.4, "Pakistan Day"
        if month == 5 and 1 <= day <= 3:
            return True, 1.8, "Eid-ul-Fitr Surge"
        if month == 7 and 8 <= day <= 10:
            return True, 1.7, "Eid-ul-Adha Surge"
        if month == 8 and day == 14:
            return True, 1.5, "Independence Day"
        if month == 12 and day == 25:
            return True, 1.3, "Quaid-e-Azam Day"

        # Ramadan seasonal month approximation (e.g. April)
        if month == 4:
            return True, 1.35, "Ramadan"

        return False, 1.0, "None"

    def generate_daily_series(
        self,
        store_id: int = 1,
        days: int = 200,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Generates daily demand records for all 10 SKUs across the requested number of days.
        """
        if end_date is None:
            end_date = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)

        start_date = end_date - timedelta(days=days)
        records = []

        # Iterate over each day
        for d in range(days):
            current_dt = start_date + timedelta(days=d)
            is_hol, hol_mult, hol_name = self.is_holiday(current_dt)

            # Day of week multiplier (Fri=4, Sat=5, Sun=6)
            dow = current_dt.weekday()
            dow_mult = 1.0
            if dow in (4, 5, 6):
                dow_mult = 1.25
            elif dow == 0:
                dow_mult = 0.85

            # Payday multiplier (days 1-5 of month)
            payday_mult = 1.20 if 1 <= current_dt.day <= 5 else 1.0

            # Generate demand for each SKU
            for sku_id, prof in SKU_DEMAND_PROFILES.items():
                base_rate = prof["base_rate"]
                base_price = prof["price"]

                # 5% chance of promo campaign (15% price cut -> 1.5x demand)
                is_promo = self.rng.random() < 0.05
                price = base_price * 0.85 if is_promo else base_price
                promo_mult = 1.50 if is_promo else 1.0

                # Mean expected demand
                expected_demand = base_rate * dow_mult * payday_mult * hol_mult * promo_mult

                # Poisson / negative binomial integer sample
                # Using Gaussian approximation with variance = mean + (mean*volatility)^2
                sigma = math.sqrt(max(1.0, expected_demand + (expected_demand * prof["volatility"]) ** 2))
                raw_units = max(0, int(round(self.rng.gauss(expected_demand, sigma))))

                # 3% chance of a random stockout day (censored demand)
                is_stockout = self.rng.random() < 0.03
                if is_stockout:
                    observed_units = max(0, int(raw_units * self.rng.uniform(0.1, 0.4)))
                else:
                    observed_units = raw_units

                records.append({
                    "store_id": store_id,
                    "sku_id": sku_id,
                    "ts": current_dt,
                    "units_removed": observed_units,
                    "units_sold": observed_units,
                    "stockout_flag": is_stockout,
                    "promo_flag": is_promo,
                    "price": price,
                    "day_of_week": dow,
                    "is_holiday": is_hol,
                    "holiday_name": hol_name
                })

        return records

    def populate_database(
        self,
        records: List[Dict],
        db: Optional[Session] = None
    ) -> int:
        """
        Inserts or merges generated records into the PostgreSQL demand_series table.
        """
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            # Batch upsert/insert
            inserted_count = 0
            for r in records:
                existing = db.query(DemandSeries).filter(
                    DemandSeries.store_id == r["store_id"],
                    DemandSeries.sku_id == r["sku_id"],
                    DemandSeries.ts == r["ts"]
                ).first()

                if existing:
                    existing.units_removed = r["units_removed"]
                    existing.units_sold = r["units_sold"]
                    existing.stockout_flag = r["stockout_flag"]
                    existing.promo_flag = r["promo_flag"]
                    existing.price = r["price"]
                else:
                    new_rec = DemandSeries(
                        store_id=r["store_id"],
                        sku_id=r["sku_id"],
                        ts=r["ts"],
                        units_removed=r["units_removed"],
                        units_sold=r["units_sold"],
                        stockout_flag=r["stockout_flag"],
                        promo_flag=r["promo_flag"],
                        price=r["price"]
                    )
                    db.add(new_rec)
                    inserted_count += 1

            db.commit()
            return inserted_count
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if close_session:
                db.close()
