from typing import List, Tuple, Dict, Optional
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset
from sqlalchemy.orm import Session

from src.shelfwatcher.db.models import DemandSeries
from src.shelfwatcher.db.session import SessionLocal


def load_demand_dataframe(store_id: int = 1, db: Optional[Session] = None) -> pd.DataFrame:
    """
    Loads demand series records from PostgreSQL demand_series table into a sorted DataFrame.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        rows = db.query(DemandSeries).filter(DemandSeries.store_id == store_id).order_by(DemandSeries.ts).all()
        data = [
            {
                "sku_id": r.sku_id,
                "ts": r.ts,
                "units_removed": r.units_removed or 0,
                "stockout_flag": bool(r.stockout_flag),
                "promo_flag": bool(r.promo_flag),
                "price": float(r.price) if r.price else 100.0,
                "day_of_week": r.ts.weekday(),
            }
            for r in rows
        ]
        df = pd.DataFrame(data)
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"])
            df = df.sort_values(["sku_id", "ts"]).reset_index(drop=True)
        return df
    finally:
        if close_db:
            db.close()


def impute_censored_demand(df: pd.DataFrame) -> pd.DataFrame:
    """
    Imputes censored demand on days where stockout_flag=True using neighbouring
    same-weekday median values (context.md Section 9.5).
    """
    df_imputed = df.copy()
    df_imputed["units_removed"] = df_imputed["units_removed"].astype(float)

    for sku_id in df_imputed["sku_id"].unique():
        mask_sku = df_imputed["sku_id"] == sku_id
        sku_df = df_imputed[mask_sku]

        # Calculate weekday medians for non-stockout days
        weekday_medians = sku_df[~sku_df["stockout_flag"]].groupby("day_of_week")["units_removed"].median().to_dict()

        for idx, row in sku_df[sku_df["stockout_flag"]].iterrows():
            fallback_val = float(weekday_medians.get(row["day_of_week"], row["units_removed"] * 1.5))
            # Impute adjusted uncensored estimate
            df_imputed.loc[idx, "units_removed"] = max(float(row["units_removed"]), fallback_val)

    return df_imputed


class TimeSeriesWindowDataset(Dataset):
    """
    PyTorch Dataset providing sliding lookback windows (X) and future target windows (y).
    """

    def __init__(
        self,
        features: np.ndarray,
        targets: np.ndarray,
        sku_indices: np.ndarray,
        lookback: int = 28,
        horizon: int = 7
    ):
        self.features = torch.tensor(features, dtype=torch.float32)
        self.targets = torch.tensor(targets, dtype=torch.float32)
        self.sku_indices = torch.tensor(sku_indices, dtype=torch.long)
        self.lookback = lookback
        self.horizon = horizon

        # Create valid sliding window start indices
        self.indices = []
        n_samples = len(features)
        for i in range(n_samples - lookback - horizon + 1):
            # Guarantee windows do not cross different SKUs
            if sku_indices[i] == sku_indices[i + lookback + horizon - 1]:
                self.indices.append(i)

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        start = self.indices[idx]
        x = self.features[start : start + self.lookback]
        y = self.targets[start + self.lookback : start + self.lookback + self.horizon]
        sku = self.sku_indices[start]
        return x, y, sku
