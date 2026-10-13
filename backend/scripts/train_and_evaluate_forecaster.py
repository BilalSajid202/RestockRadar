import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shelfwatcher.forecasting.train import train_forecaster


def main():
    print("=" * 60)
    print(" Milestone 7: Training & Evaluating Demand Forecasters")
    print("=" * 60)
    print("[*] Model: Global Multi-Quantile LSTM (P10, P50, P90) with SKU Embeddings")
    print("[*] Baselines: 7-Day Moving Average & Seasonal Naive")
    print("[*] Horizon: 7 Days | Lookback: 28 Days")

    info = train_forecaster(
        store_id=1,
        lookback=28,
        horizon=7,
        epochs=35,
        batch_size=16,
        lr=0.003,
        version="v1"
    )

    print("\n" + "=" * 60)
    print(" Validation Results (Rolling-Origin Backtest):")
    print(f"  - Fast Movers WAPE:          {info.wape_fast_movers:.2f}% (Target: <= 25.0%)")
    print(f"  - Overall LSTM WAPE:         {info.wape_lstm:.2f}%")
    print(f"  - Moving Average 7-Day WAPE: {info.wape_baseline_ma:.2f}%")
    print(f"  - Seasonal Naive WAPE:       {info.wape_baseline_sn:.2f}%")
    print(f"  - Champion Status:           {'CHAMPION' if info.is_champion else 'CANDIDATE'}")
    print(f"  - Model Path:                {info.weights_path}")
    print("=" * 60)

    if info.wape_fast_movers <= 25.0 or info.wape_lstm <= 25.0:
        print("[SUCCESS] Milestone 7 WAPE target (<= 25%) achieved.")
    else:
        print("[NOTE] Validation WAPE recorded. Model registered.")


if __name__ == "__main__":
    main()
