import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import numpy as np
from PIL import Image

from src.shelfwatcher.simulation.mini_shelf_gen import ShelfSceneGenerator
from src.shelfwatcher.simulation.demand_sim import SKU_DEMAND_PROFILES


class ShelfDemandSimulator:
    """
    Implements the Shelf-Demand Link (context.md Section 17.5).
    As simulated demand depletes units on the shelf, this class renders/serves
    the visually matching shelf image sequence (full -> depleted -> empty -> refilled)
    and saves them to the replay folder.
    """

    def __init__(
        self,
        replay_dir: str = "data/replay",
        shelf_capacity_per_sku: int = 5,
        img_width: int = 960,
        img_height: int = 960
    ):
        self.replay_dir = replay_dir
        self.capacity = shelf_capacity_per_sku
        self.generator = ShelfSceneGenerator(img_width, img_height)

        # On-shelf inventory tracking: sku_id -> count
        self.inventory: Dict[int, int] = {sku_id: self.capacity for sku_id in SKU_DEMAND_PROFILES.keys()}

    def apply_hourly_demand(self, hourly_demand: Dict[int, int]) -> float:
        """
        Subtracts hourly demand from on-shelf inventory and returns the new fill percentage.
        """
        for sku_id, demand in hourly_demand.items():
            if sku_id in self.inventory:
                self.inventory[sku_id] = max(0, self.inventory[sku_id] - demand)

        total_units = sum(self.inventory.values())
        max_units = len(self.inventory) * self.capacity
        fill_pct = (total_units / max_units) * 100.0 if max_units > 0 else 0.0
        return fill_pct

    def deliver_replenishment(self, sku_id: int, qty: int) -> float:
        """
        Simulates supplier delivery replenishment arriving on the shelf.
        """
        if sku_id in self.inventory:
            self.inventory[sku_id] = min(self.capacity, self.inventory[sku_id] + qty)

        total_units = sum(self.inventory.values())
        max_units = len(self.inventory) * self.capacity
        return (total_units / max_units) * 100.0

    def generate_replay_sequence(
        self,
        start_time: datetime,
        hours: int = 48,
        interval_hours: int = 3,
        auto_delivery_at_hour: int = 36
    ) -> List[str]:
        """
        Generates a 48-hour continuous sequence of timestamped images reflecting
        gradual customer depletion followed by a scheduled delivery replenishment.
        """
        os.makedirs(self.replay_dir, exist_ok=True)
        generated_paths = []

        # Reset inventory to full at start
        self.inventory = {sku_id: self.capacity for sku_id in SKU_DEMAND_PROFILES.keys()}

        for h in range(0, hours, interval_hours):
            ts = start_time + timedelta(hours=h)

            # Customer removals per 3-hour block
            hourly_demand = {
                sku: 1 if (h % 6 == 0 and sku in (1, 4, 5)) else (1 if (h % 9 == 0) else 0)
                for sku in self.inventory.keys()
            }

            fill_pct = self.apply_hourly_demand(hourly_demand)

            # Simulate delivery arrival
            if h == auto_delivery_at_hour:
                for sku in self.inventory.keys():
                    self.deliver_replenishment(sku, 5)
                fill_pct = 100.0

            # Calculate gap probability matching current depletion level
            # 100% fill -> 0.05 gap_p; 20% fill -> 0.80 gap_p
            gap_prob = max(0.05, min(0.95, 1.0 - (fill_pct / 100.0)))

            # Render scene
            seed = int(ts.timestamp()) % 100000
            img, _ = self.generator.generate_scene(
                session_id=1,
                scene_seed=seed,
                gap_prob=gap_prob
            )

            filename = ts.strftime("%Y%m%d_%H%M%S.jpg")
            filepath = os.path.join(self.replay_dir, filename)
            img.save(filepath, quality=90)
            generated_paths.append(filepath)

        return generated_paths
