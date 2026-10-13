from datetime import datetime, timezone, timedelta
import pytest

from src.shelfwatcher.forecasting.baselines import MovingAverageBaseline, SeasonalNaiveBaseline, compute_wape
from src.shelfwatcher.forecasting.stockout import estimate_stockout_timestamp
from src.shelfwatcher.forecasting.predict import predict, Forecast
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.db.models import Forecast as DBForecast


def test_moving_average_baseline():
    ma = MovingAverageBaseline(window=7)
    series = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
    res = ma.predict(series, horizon_days=7)

    assert len(res["p50"]) == 7
    assert len(res["p10"]) == 7
    assert len(res["p90"]) == 7
    assert res["p50"][0] == 16.0
    assert res["p10"][0] < res["p50"][0] < res["p90"][0]


def test_seasonal_naive_baseline():
    sn = SeasonalNaiveBaseline(season_length=7)
    # 2 weeks of repeating weekday pattern
    series = [5.0, 6.0, 7.0, 8.0, 15.0, 20.0, 25.0] * 2
    res = sn.predict(series, horizon_days=7)

    assert len(res["p50"]) == 7
    # Saturday and Sunday should reflect weekend surges
    assert res["p50"][4] == 15.0
    assert res["p50"][5] == 20.0
    assert res["p50"][6] == 25.0


def test_wape_computation():
    actual = [100.0, 200.0]
    forecast = [90.0, 210.0]  # total error: 10 + 10 = 20; total actual: 300
    wape = compute_wape(actual, forecast)
    assert abs(wape - (20.0 / 300.0 * 100.0)) < 0.01


def test_stockout_depletion_simulation():
    start = datetime(2026, 10, 8, 8, 0, 0, tzinfo=timezone.utc)
    # Current units: 10
    # Expected daily demand: 20 units/day
    p50 = [20.0] * 7
    p90 = [25.0] * 7

    stockout_at = estimate_stockout_timestamp(
        current_units=10,
        daily_forecast_p50=p50,
        daily_forecast_p90=p90,
        start_time=start,
        min_display=0,
        conservative=False
    )

    assert stockout_at is not None
    assert stockout_at > start
    # 10 units depleted in less than 24 hours at 20 units/day rate
    assert stockout_at < start + timedelta(hours=24)


def test_insufficient_history_fallback():
    # Predict for SKU 99 (new SKU with 0 history)
    fc = predict(sku_id=99, as_of=datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc))

    assert fc.used_fallback is True
    assert "baseline" in fc.model_version
    assert len(fc.p50) == 7
    assert len(fc.p10) == 7
    assert len(fc.p90) == 7


def test_predict_interface_contract():
    # Predict for Milk (SKU 1) which has 200 days of bootstrapped history
    fc = predict(sku_id=1, as_of=datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc))

    assert isinstance(fc, Forecast)
    assert fc.sku_id == 1
    assert fc.horizon_days == 7
    assert len(fc.p50) == 7
    assert all(v >= 0 for v in fc.p50)

    # Verify saved in PostgreSQL forecasts table
    db = SessionLocal()
    try:
        saved = db.query(DBForecast).filter(DBForecast.sku_id == 1).order_by(DBForecast.forecast_id.desc()).first()
        assert saved is not None
        assert saved.horizon_days == 7
    finally:
        db.close()
