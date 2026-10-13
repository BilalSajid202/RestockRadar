import os
import sys

# Ensure backend root is in sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import argparse
import uvicorn
from src.shelfwatcher.db.init_db import init_db


def main():
    parser = argparse.ArgumentParser(description="Shelf Watcher (Restock Radar) Unified Runner")
    parser.add_argument("--init-db", action="store_true", help="Initialize database schema and seed data")
    parser.add_argument("--port", type=int, default=8000, help="Port for FastAPI server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host for FastAPI server")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn hot reload")
    args = parser.parse_args()

    print("=" * 60)
    print(" Restock Radar — See -> Predict -> Act -> Verify")
    print("=" * 60)

    # Initialize DB if requested or database doesn't exist
    init_db(seed=True)
    print("[OK] Database verified and seeded.")

    print(f"[*] Starting API on http://{args.host}:{args.port}")
    uvicorn.run("src.shelfwatcher.api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
