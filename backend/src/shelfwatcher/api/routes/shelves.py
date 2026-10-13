from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.shelfwatcher.db.session import get_db
from src.shelfwatcher.db.models import Shelf, ShelfSnapshot, Planogram, SKU, Camera, Frame

router = APIRouter(prefix="/shelves", tags=["Shelves"])


@router.get("")
def list_shelves(db: Session = Depends(get_db)):
    """Lists all shelves with their latest snapshot metrics."""
    shelves = db.query(Shelf).all()
    results = []

    for s in shelves:
        latest_snap = db.query(ShelfSnapshot).filter(
            ShelfSnapshot.shelf_id == s.shelf_id
        ).order_by(desc(ShelfSnapshot.snapshot_id)).first()

        results.append({
            "shelf_id": s.shelf_id,
            "camera_id": s.camera_id,
            "name": s.name,
            "aisle": s.aisle,
            "level": s.level,
            "total_facings": s.total_facings,
            "fill_pct": round(latest_snap.fill_pct, 1) if latest_snap else 100.0,
            "item_count": latest_snap.item_count if latest_snap else s.total_facings,
            "gap_count": latest_snap.gap_count if latest_snap else 0,
            "status": latest_snap.status if latest_snap else "OK",
            "last_updated": latest_snap.captured_at.isoformat() if latest_snap else None
        })

    return results


@router.get("/{shelf_id}/state")
def get_shelf_state(shelf_id: int, db: Session = Depends(get_db)):
    """Fetches detailed state of a shelf including planogram and latest image."""
    shelf = db.query(Shelf).filter(Shelf.shelf_id == shelf_id).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")

    latest_snap = db.query(ShelfSnapshot).filter(
        ShelfSnapshot.shelf_id == shelf_id
    ).order_by(desc(ShelfSnapshot.snapshot_id)).first()

    # Get latest frame for camera
    latest_frame = db.query(Frame).filter(
        Frame.camera_id == shelf.camera_id,
        Frame.valid_flag == True
    ).order_by(desc(Frame.frame_id)).first()

    # Get planogram details
    planograms = db.query(Planogram, SKU).join(SKU, Planogram.sku_id == SKU.sku_id).filter(
        Planogram.shelf_id == shelf_id
    ).all()

    planogram_list = []
    for pl, sku in planograms:
        planogram_list.append({
            "zone": pl.zone,
            "sku_id": sku.sku_id,
            "name_en": sku.name_en,
            "name_ur": sku.name_ur,
            "category": sku.category,
            "unit_price": float(sku.unit_price),
            "facings": pl.facings,
            "depth_capacity": pl.depth_capacity
        })

    return {
        "shelf_id": shelf.shelf_id,
        "name": shelf.name,
        "aisle": shelf.aisle,
        "level": shelf.level,
        "total_facings": shelf.total_facings,
        "roi_polygon": shelf.roi_polygon,
        "latest_snapshot": {
            "item_count": latest_snap.item_count if latest_snap else 0,
            "gap_count": latest_snap.gap_count if latest_snap else 0,
            "fill_pct": latest_snap.fill_pct if latest_snap else 0.0,
            "status": latest_snap.status if latest_snap else "UNKNOWN",
            "captured_at": latest_snap.captured_at.isoformat() if latest_snap else None
        } if latest_snap else None,
        "latest_frame_path": latest_frame.path.replace("\\", "/") if latest_frame else None,
        "planogram": planogram_list
    }


@router.get("/{shelf_id}/history")
def get_shelf_history(shelf_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """Returns historical snapshots for time-series charts."""
    snaps = db.query(ShelfSnapshot).filter(
        ShelfSnapshot.shelf_id == shelf_id
    ).order_by(desc(ShelfSnapshot.snapshot_id)).limit(limit).all()

    # Reverse to chronological order
    snaps.reverse()
    return [
        {
            "snapshot_id": s.snapshot_id,
            "captured_at": s.captured_at.isoformat(),
            "fill_pct": s.fill_pct,
            "item_count": s.item_count,
            "gap_count": s.gap_count,
            "status": s.status
        }
        for s in snaps
    ]
