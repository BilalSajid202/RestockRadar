# Restock Radar (Shelf Watcher)

Autonomous Closed-Loop Retail Inventory Perception & Restocking System (**See → Predict → Act → Verify**).

---

## 📁 Repository Structure

```text
RestockRadar/
├── backend/
│   ├── data/                 # Raw frames, YOLO dataset, replay sequences, sim demand
│   ├── docs/                 # DECISIONS.md & DATA_CARD.md
│   ├── models/               # Weights and registry.json
│   ├── scripts/              # Dataset generation, evaluation & verification runners
│   ├── src/shelfwatcher/     # Vision, forecasting, reorder, agent, ingestion & FastAPI
│   ├── tests/                # Unit, integration, and adversarial tests
│   ├── run.py                # Unified backend startup entrypoint
│   ├── requirements.txt      # Python dependencies
│   └── .env                  # PostgreSQL database and runtime configuration
├── frontend/                 # Next.js (React + TypeScript) Dashboard
│   ├── src/app/              # Dashboard pages, layout, and modern glassmorphism styles
│   └── package.json          # Node dependencies
└── context.md                # Complete specification & contracts
```

---

## 🚀 Running the Project

### 1. Backend (FastAPI + Ingestion & Simulation)
```bash
# Inside backend/ or from workspace root
python backend/run.py
```
* API available at: `http://127.0.0.1:8000`
* Interactive API Documentation: `http://127.0.0.1:8000/docs`

### 2. Frontend (Next.js Dashboard)
```bash
cd frontend
npm run dev
```
* Dashboard available at: `http://localhost:3000`

---

## 🧪 Testing Backend
```bash
# Run all unit tests
python -m pytest backend/tests
```