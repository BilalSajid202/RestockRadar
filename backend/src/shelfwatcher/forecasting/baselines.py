from typing import List, Dict
import numpy as np


class MovingAverageBaseline:
    """
    Moving Average baseline (7-day or 14-day window).
    Produces identical point forecast across horizon_days.
    """

    def __init__(self, window: int = 7):
        self.window = window

    def predict(self, series: List[float], horizon_days: int = 7) -> Dict[str, List[float]]:
        if not series:
            val = 0.0
        else:
            recent = series[-self.window:] if len(series) >= self.window else series
            val = float(np.mean(recent))

        # Quantile estimates: point estimate for p50, ±20% for p10/p90
        p50 = [round(max(0.0, val), 2)] * horizon_days
        p10 = [round(max(0.0, val * 0.8), 2)] * horizon_days
        p90 = [round(max(0.0, val * 1.2), 2)] * horizon_days

        return {"p10": p10, "p50": p50, "p90": p90}


class SeasonalNaiveBaseline:
    """
    Seasonal Naive baseline (takes the same weekday from the previous week).
    """

    def __init__(self, season_length: int = 7):
        self.season_length = season_length

    def predict(self, series: List[float], horizon_days: int = 7) -> Dict[str, List[float]]:
        if len(series) < self.season_length:
            return MovingAverageBaseline().predict(series, horizon_days)

        recent_season = series[-self.season_length:]
        p50 = []
        for i in range(horizon_days):
            val = float(recent_season[i % self.season_length])
            p50.append(round(max(0.0, val), 2))

        p10 = [round(max(0.0, v * 0.8), 2) for v in p50]
        p90 = [round(max(0.0, v * 1.2), 2) for v in p50]

        return {"p10": p10, "p50": p50, "p90": p90}


def compute_wape(actual: List[float], forecast: List[float]) -> float:
    """
    Weighted Absolute Percentage Error (WAPE) = sum(|actual - forecast|) / sum(actual).
    Bounded in percentage.
    """
    actual_arr = np.array(actual, dtype=float)
    forecast_arr = np.array(forecast, dtype=float)

    total_actual = float(np.sum(actual_arr))
    if total_actual <= 0:
        return 0.0

    wape = float(np.sum(np.abs(actual_arr - forecast_arr))) / total_actual
    return round(wape * 100.0, 2)
