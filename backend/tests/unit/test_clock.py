from datetime import datetime, timezone
from src.shelfwatcher import clock


def test_clock_now_default():
    t = clock.now()
    assert t.tzinfo is not None
    assert t.tzinfo == timezone.utc


def test_clock_sim_time_override():
    sim_target = datetime(2026, 11, 15, 14, 30, 0, tzinfo=timezone.utc)
    clock.set_sim_time(sim_target)

    t = clock.now()
    assert t == sim_target

    # Reset
    clock.set_sim_time(None)
    assert clock.now() != sim_target
