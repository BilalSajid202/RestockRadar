from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple


# Normalized retail hourly depletion profile across 24 hours
HOURLY_PROFILE = [
    0.01, 0.00, 0.00, 0.00, 0.00, 0.01,  # 00:00 - 05:00 (closed/night)
    0.02, 0.04, 0.06, 0.07, 0.08, 0.08,  # 06:00 - 11:00 (morning)
    0.09, 0.07, 0.06, 0.06, 0.07, 0.09,  # 12:00 - 17:00 (afternoon)
    0.10, 0.08, 0.05, 0.03, 0.01, 0.01   # 18:00 - 23:00 (evening)
]


def estimate_stockout_timestamp(
    current_units: int,
    daily_forecast_p50: List[float],
    daily_forecast_p90: List[float],
    start_time: datetime,
    min_display: int = 0,
    conservative: bool = False
) -> Optional[datetime]:
    """
    Simulates inventory depletion from current on-shelf stock S0 using hourly demand distribution
    to determine the exact stockout timestamp (context.md Section 9.5).
    """
    if current_units <= min_display:
        return start_time

    # Use p90 in conservative mode for earliest plausible stockout, else p50 point forecast
    daily_demand = daily_forecast_p90 if conservative else daily_forecast_p50

    remaining_units = float(current_units)
    current_sim_time = start_time

    # Simulate hour-by-hour depletion across the horizon days
    for day_idx, expected_day_units in enumerate(daily_demand):
        for hour in range(24):
            profile_weight = HOURLY_PROFILE[hour]
            hourly_rate = expected_day_units * profile_weight

            remaining_units -= hourly_rate
            current_sim_time += timedelta(hours=1)

            if remaining_units <= min_display:
                return current_sim_time

    # If inventory sustains beyond the horizon, stockout is not imminent
    return None
