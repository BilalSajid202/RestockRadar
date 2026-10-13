from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from src.shelfwatcher import clock
from src.shelfwatcher.ingestion.pipeline import process_camera_frame
from src.shelfwatcher.ingestion.replay import ReplaySource
from src.shelfwatcher.db.session import SessionLocal
from src.shelfwatcher.db.models import Camera, ShelfSnapshot, RestockTicket


class ScenarioRunner:
    """
    Orchestrates time-stepped simulation runs using SIM_NOW to advance virtual time
    and test pipeline workflows synchronously (context.md Section 17.6).
    """

    def __init__(self, camera_id: int = 1, replay_folder: str = "data/replay"):
        self.camera_id = camera_id
        self.replay_folder = replay_folder
        self.current_time = clock.now()

    def set_time(self, target_time: datetime):
        """Sets the simulation clock."""
        self.current_time = target_time
        clock.set_sim_time(target_time)

    def advance_time(self, delta_minutes: int = 15) -> datetime:
        """Advances the simulation clock by the specified delta."""
        self.current_time += timedelta(minutes=delta_minutes)
        clock.set_sim_time(self.current_time)
        return self.current_time

    def step(self) -> Dict[str, Any]:
        """
        Executes one discrete simulation step:
        1. Ingests current camera frame via ReplaySource.
        2. Triggers quality gate, detection, and shelf snapshot update.
        """
        source = ReplaySource(folder_path=self.replay_folder, camera_id=self.camera_id, loop=True)
        res = process_camera_frame(
            camera_id=self.camera_id,
            source=source,
            output_dir="data/raw"
        )
        return {
            "sim_time": self.current_time.isoformat(),
            "pipeline_result": res
        }

    def run_sequence(self, steps: int = 8, step_minutes: int = 15) -> List[Dict[str, Any]]:
        """Runs a sequence of simulated steps advancing time on each iteration."""
        history = []
        for _ in range(steps):
            step_result = self.step()
            history.append(step_result)
            self.advance_time(step_minutes)
        return history
