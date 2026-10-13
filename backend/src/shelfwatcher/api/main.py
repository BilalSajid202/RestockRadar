import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.shelfwatcher.config import settings
from src.shelfwatcher.api.routes.shelves import router as shelves_router
from src.shelfwatcher.api.routes.simulation import router as simulation_router
from src.shelfwatcher.api.routes.tickets import router as tickets_router

app = FastAPI(
    title="Restock Radar API",
    description="Closed-loop retail inventory perception and autonomous restocking system",
    version="1.0.0"
)

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount data folder to serve captured frames and replay images
backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
data_dir = os.path.join(backend_root, "data")
if os.path.exists(data_dir):
    app.mount("/static/data", StaticFiles(directory=data_dir), name="data")

# Register routers
app.include_router(shelves_router)
app.include_router(simulation_router)
app.include_router(tickets_router)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Restock Radar",
        "agent_enabled": settings.agent_enabled,
        "dry_run": settings.dry_run,
        "sim_now": settings.sim_now
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
