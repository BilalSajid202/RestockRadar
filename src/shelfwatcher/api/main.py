from fastapi import FastAPI
from src.shelfwatcher.config import settings

app = FastAPI(
    title="Restock Radar API",
    description="Closed-loop retail inventory perception and autonomous restocking system",
    version="1.0.0"
)


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
