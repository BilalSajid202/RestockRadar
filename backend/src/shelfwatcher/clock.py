from datetime import datetime, timezone
from typing import Optional
from src.shelfwatcher.config import settings

# Global override for simulation clock during runtime
_sim_clock_override: Optional[datetime] = None


def set_sim_time(sim_time: Optional[datetime]) -> None:
    """Explicitly set or clear the in-memory simulation clock."""
    global _sim_clock_override
    if sim_time is not None and sim_time.tzinfo is None:
        _sim_clock_override = sim_time.replace(tzinfo=timezone.utc)
    else:
        _sim_clock_override = sim_time


def now() -> datetime:
    """
    Returns current timestamp in UTC.
    If an in-memory simulation clock or settings.sim_now is set, returns simulated time.
    """
    global _sim_clock_override
    if _sim_clock_override is not None:
        return _sim_clock_override

    if settings.sim_now:
        try:
            # Parse ISO formatted string or space-separated timestamp
            parsed = datetime.fromisoformat(settings.sim_now)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass

    return datetime.now(timezone.utc)
