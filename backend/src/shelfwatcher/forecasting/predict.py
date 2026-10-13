from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import os
import numpy as np
import torch
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.shelfwatcher.db.models import DemandSeries, ShelfSnapshot, Forecast as DBForecast, Planogram, SKU
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.forecasting.baselines import MovingAverageBaseline
from src.shelfwatcher.forecasting.stockout import estimate_stockout_timestamp
from src.shelfwatcher.forecasting.lstm import QuantileLSTMForecaster
from src.shelfwatcher import clock


@dataclass
class Forecast:
    sku_id: int
    generated_at: datetime
    horizon_days: int
    p10: List[float]
    p50: List[float]
    p90: List[float]
    predicted_stockout_at: Optional[datetime]
    model_version: str
    used_fallback: bool


# Cached forecaster instance
_cached_forecaster: Optional[QuantileLSTMForecaster] = None


def get_trained_forecaster(version: str = "v1") -> Optional[QuantileLSTMForecaster]:
    global _cached_forecaster
    if _cached_forecaster is not None:
        return _cached_forecaster

    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    weights_path = os.path.join(backend_root, "models", "forecaster", version, "best.pt")

    if os.path.exists(weights_path):
        try:
            model = QuantileLSTMForecaster(
                num_skus=20,
                sku_embed_dim=8,
                num_features=4,
                hidden_dim=48,
                num_layers=2,
                horizon=7,
                num_quantiles=3
            )
            model.load_state_dict(torch.load(weights_path, weights_only=True))
            model.eval()
            _cached_forecaster = model
            return _cached_forecaster
        except Exception:
            return None
    return None


def predict(
    sku_id: int,
    as_of: Optional[datetime] = None,
    store_id: int = 1,
    db: Optional[Session] = None
) -> Forecast:
    """
    Produces 7-day quantile demand forecasts (P10, P50, P90) and estimated stockout timestamp
    for a given SKU according to context.md Section 9.5.
    """
    if as_of is None:
        as_of = clock.now()

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # 1. Fetch historical demand series for this SKU
        rows = db.query(DemandSeries).filter(
            DemandSeries.store_id == store_id,
            DemandSeries.sku_id == sku_id,
            DemandSeries.ts <= as_of
        ).order_by(DemandSeries.ts).all()

        history_units = [float(r.units_removed or 0) for r in rows]
        used_fallback = False
        model_version = "v1"

        # Rule: If SKU history < 28 days -> baseline fallback
        if len(history_units) < 28:
            used_fallback = True
            model_version = "baseline_ma7"
            ma = MovingAverageBaseline(window=7)
            preds = ma.predict(history_units, horizon_days=7)
            p10, p50, p90 = preds["p10"], preds["p50"], preds["p90"]
        else:
            forecaster = get_trained_forecaster()
            if forecaster is not None:
                # Prepare features for last 28 days
                recent_rows = rows[-28:]
                feats = []
                for r in recent_rows:
                    log_u = float(np.log1p(r.units_removed or 0))
                    dow = r.ts.weekday() / 6.0
                    promo = 1.0 if r.promo_flag else 0.0
                    prc = float(r.price or 100.0) / 1000.0
                    feats.append([log_u, dow, promo, prc])

                x_t = torch.tensor([feats], dtype=torch.float32)
                sku_t = torch.tensor([sku_id], dtype=torch.long)

                with torch.no_grad():
                    p_raw = forecaster(x_t, sku_t)[0].numpy()  # (7, 3)

                # Invert log1p for P10, P50, P90
                p10 = [round(float(np.expm1(max(0.0, v))), 2) for v in p_raw[:, 0]]
                p50 = [round(float(np.expm1(max(0.0, v))), 2) for v in p_raw[:, 1]]
                p90 = [round(float(np.expm1(max(0.0, v))), 2) for v in p_raw[:, 2]]
            else:
                used_fallback = True
                model_version = "baseline_ma7"
                ma = MovingAverageBaseline(window=7)
                preds = ma.predict(history_units, horizon_days=7)
                p10, p50, p90 = preds["p10"], preds["p50"], preds["p90"]

        # 2. Get current on-shelf inventory S0
        latest_snap = db.query(ShelfSnapshot).order_by(desc(ShelfSnapshot.snapshot_id)).first()
        current_on_shelf = latest_snap.item_count if latest_snap else 5

        # 3. Simulate depletion to estimate stockout timestamp
        stockout_at = estimate_stockout_timestamp(
            current_units=current_on_shelf,
            daily_forecast_p50=p50,
            daily_forecast_p90=p90,
            start_time=as_of,
            min_display=0,
            conservative=False
        )

        # 4. Record forecast in database if SKU is registered in store
        sku_exists = db.query(SKU).filter(SKU.sku_id == sku_id).first() is not None
        if sku_exists:
            db_fc = DBForecast(
                sku_id=sku_id,
                generated_at=as_of,
                horizon_days=7,
                p10=p10,
                p50=p50,
                p90=p90,
                predicted_stockout_at=stockout_at,
                model_version=model_version,
                used_fallback=used_fallback
            )
            db.add(db_fc)
            db.commit()

        return Forecast(
            sku_id=sku_id,
            generated_at=as_of,
            horizon_days=7,
            p10=p10,
            p50=p50,
            p90=p90,
            predicted_stockout_at=stockout_at,
            model_version=model_version,
            used_fallback=used_fallback
        )

    finally:
        if close_db:
            db.close()
