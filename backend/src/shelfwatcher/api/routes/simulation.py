from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.shelfwatcher import clock
from src.shelfwatcher.config import settings
from src.shelfwatcher.simulation.scenario_runner import ScenarioRunner
from src.shelfwatcher.db.session import get_db

router = APIRouter(prefix="/sim", tags=["Simulation"])

scenario_runner = ScenarioRunner(camera_id=1)


class AdvanceRequest(BaseModel):
    delta_minutes: int = 15


@router.get("/status")
def get_sim_status():
    """Returns current simulation clock and system mode flags."""
    return {
        "sim_now": clock.now().isoformat(),
        "is_simulated": settings.sim_now is not None or clock._sim_clock_override is not None,
        "agent_enabled": settings.agent_enabled,
        "dry_run": settings.dry_run,
        "capture_interval_min": settings.capture_interval_min
    }


@router.post("/advance")
def advance_simulation(req: AdvanceRequest = Body(...)):
    """Advances virtual simulation clock and executes one pipeline step."""
    new_time = scenario_runner.advance_time(delta_minutes=req.delta_minutes)
    step_result = scenario_runner.step()

    return {
        "advanced_to": new_time.isoformat(),
        "delta_minutes": req.delta_minutes,
        "pipeline_result": step_result["pipeline_result"]
    }


@router.post("/reset")
def reset_simulation():
    """Resets the simulation clock override to real system time."""
    clock.set_sim_time(None)
    scenario_runner.current_time = clock.now()
    return {
        "status": "reset",
        "current_time": clock.now().isoformat()
    }
