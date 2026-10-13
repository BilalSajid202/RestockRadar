from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Set
from sqlalchemy.orm import Session

from src.shelfwatcher.vision.tracker import Track, ShelfTracker
from src.shelfwatcher.db.models import Event, DemandSeries
from src.shelfwatcher.config import settings
from src.shelfwatcher import clock


@dataclass
class PendingRemoval:
    track_id: int
    sku_id: Optional[int]
    zone_idx: int
    removed_at: datetime
    initial_absence_time: datetime


class EventProcessor:
    """
    Manages shelf state transitions, lifecycle events, put-back resolutions,
    and updates the demand_series table (context.md Section 9.4).
    """

    def __init__(
        self,
        shelf_id: int,
        store_id: int = 1,
        miss_tolerance_frames: int = settings.miss_tolerance_frames,
        putback_window_min: int = settings.putback_window_min,
        refill_delta: float = settings.refill_delta
    ):
        self.shelf_id = shelf_id
        self.store_id = store_id
        self.miss_tolerance_frames = miss_tolerance_frames
        self.putback_window = timedelta(minutes=putback_window_min)
        self.refill_delta = refill_delta

        self.last_fill_pct: Optional[float] = None
        self.pending_removals: Dict[int, PendingRemoval] = {}  # track_id -> PendingRemoval
        self.previous_tracks: Dict[int, Track] = {}
        self.observed_gaps_count: int = 0

    def process_frame_tracks(
        self,
        current_tracks: List[Track],
        fill_pct: float,
        gap_count: int,
        timestamp: Optional[datetime] = None,
        db_session: Optional[Session] = None
    ) -> List[Dict[str, Any]]:
        """
        Processes track updates for a frame, identifies additions, removals,
        put-backs, refills, and gap transitions. Emits list of generated event dicts.
        """
        if timestamp is None:
            timestamp = clock.now()

        events_generated: List[Dict[str, Any]] = []
        current_track_dict = {t.track_id: t for t in current_tracks}

        # 1. Detect Refill event: fill_pct rises by >= REFILL_DELTA
        if self.last_fill_pct is not None:
            delta = fill_pct - self.last_fill_pct
            if delta >= self.refill_delta:
                events_generated.append({
                    "shelf_id": self.shelf_id,
                    "sku_id": None,
                    "type": "SHELF_REFILLED",
                    "track_id": None,
                    "occurred_at": timestamp,
                    "meta": {"previous_fill": self.last_fill_pct, "new_fill": fill_pct, "delta": delta}
                })

        # 2. Detect Gap Transitions
        if gap_count > self.observed_gaps_count:
            events_generated.append({
                "shelf_id": self.shelf_id,
                "sku_id": None,
                "type": "GAP_OPENED",
                "track_id": None,
                "occurred_at": timestamp,
                "meta": {"previous_gaps": self.observed_gaps_count, "new_gaps": gap_count}
            })
        elif gap_count < self.observed_gaps_count:
            events_generated.append({
                "shelf_id": self.shelf_id,
                "sku_id": None,
                "type": "GAP_CLOSED",
                "track_id": None,
                "occurred_at": timestamp,
                "meta": {"previous_gaps": self.observed_gaps_count, "new_gaps": gap_count}
            })
        self.observed_gaps_count = gap_count
        self.last_fill_pct = fill_pct

        # 3. Check for Put-Backs among active tracks
        handled_putbacks: Set[int] = set()
        for t in current_tracks:
            if t.state == "ACTIVE":
                matched_rem_id = None
                if t.track_id in self.pending_removals:
                    matched_rem_id = t.track_id
                else:
                    # Match pending removal by zone and SKU
                    for rem_id, rem in list(self.pending_removals.items()):
                        if rem.zone_idx == t.zone_idx and (rem.sku_id == t.sku_id or rem.sku_id is None):
                            matched_rem_id = rem_id
                            break

                if matched_rem_id is not None:
                    handled_putbacks.add(t.track_id)
                    rem = self.pending_removals.pop(matched_rem_id)
                    events_generated.append({
                        "shelf_id": self.shelf_id,
                        "sku_id": t.sku_id or rem.sku_id,
                        "type": "PUT_BACK",
                        "track_id": t.track_id,
                        "occurred_at": timestamp,
                        "meta": {
                            "absent_duration_sec": (timestamp - rem.initial_absence_time).total_seconds(),
                            "zone": t.zone_idx
                        }
                    })

        # 4. Check for New Items Added
        for t_id, t in current_track_dict.items():
            if t_id not in self.previous_tracks and t_id not in self.pending_removals and t_id not in handled_putbacks:
                events_generated.append({
                    "shelf_id": self.shelf_id,
                    "sku_id": t.sku_id,
                    "type": "ITEM_ADDED",
                    "track_id": t.track_id,
                    "occurred_at": timestamp,
                    "meta": {"zone": t.zone_idx}
                })

        # 5. Check for newly absent items exceeding MISS_TOLERANCE_FRAMES
        for t_id, prev_t in self.previous_tracks.items():
            curr = current_track_dict.get(t_id)
            if curr is None or curr.state == "MISSED":
                if t_id not in self.pending_removals:
                    # Item absent for > miss tolerance
                    self.pending_removals[t_id] = PendingRemoval(
                        track_id=t_id,
                        sku_id=prev_t.sku_id,
                        zone_idx=prev_t.zone_idx,
                        removed_at=timestamp,
                        initial_absence_time=prev_t.last_seen
                    )

        # 6. Finalize Pending Removals that exceeded PUTBACK_WINDOW_MIN
        expired_track_ids = []
        final_removals: List[PendingRemoval] = []
        for t_id, rem in self.pending_removals.items():
            if (timestamp - rem.initial_absence_time) >= self.putback_window:
                expired_track_ids.append(t_id)
                final_removals.append(rem)
                events_generated.append({
                    "shelf_id": self.shelf_id,
                    "sku_id": rem.sku_id,
                    "type": "ITEM_REMOVED",
                    "track_id": rem.track_id,
                    "occurred_at": timestamp,
                    "meta": {"zone": rem.zone_idx}
                })

        for t_id in expired_track_ids:
            del self.pending_removals[t_id]

        # Update previous tracks
        self.previous_tracks = current_track_dict

        # 7. Persist to DB if session provided
        if db_session is not None and events_generated:
            self._save_events_and_demand(events_generated, final_removals, timestamp, db_session)

        return events_generated

    def _save_events_and_demand(
        self,
        events: List[Dict[str, Any]],
        confirmed_removals: List[PendingRemoval],
        timestamp: datetime,
        db: Session
    ):
        """Writes Event records and increments demand_series units_removed."""
        for ev in events:
            db_ev = Event(
                shelf_id=ev["shelf_id"],
                sku_id=ev["sku_id"],
                type=ev["type"],
                track_id=ev["track_id"],
                occurred_at=ev["occurred_at"],
                meta=ev.get("meta")
            )
            db.add(db_ev)

        # Aggregate confirmed ITEM_REMOVED into demand_series (hourly slot)
        removals_by_sku: Dict[int, int] = {}
        for r in confirmed_removals:
            if r.sku_id is not None:
                removals_by_sku[r.sku_id] = removals_by_sku.get(r.sku_id, 0) + 1

        hour_ts = timestamp.replace(minute=0, second=0, microsecond=0)
        for sku_id, count in removals_by_sku.items():
            series = db.query(DemandSeries).filter(
                DemandSeries.store_id == self.store_id,
                DemandSeries.sku_id == sku_id,
                DemandSeries.ts == hour_ts
            ).first()

            if series is not None:
                series.units_removed = (series.units_removed or 0) + count
            else:
                new_series = DemandSeries(
                    store_id=self.store_id,
                    sku_id=sku_id,
                    ts=hour_ts,
                    units_removed=count,
                    stockout_flag=False,
                    promo_flag=False
                )
                db.add(new_series)

        db.commit()
