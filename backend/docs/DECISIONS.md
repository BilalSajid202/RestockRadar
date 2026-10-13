# Decisions Changelog

| Date | Decision | Reason |
|---|---|---|
| 2026-10-07 | Adopt standard repository layout from context.md Section 8 | Clean separation of vision, forecasting, agent, and genai modules for testability |
| 2026-10-07 | Set up Milestone 1 dataset generator with 10 mini-shelf SKUs and explicit gap class | Facilitate repeatable synthetic & photo benchmark without live store feed dependence |
| 2026-10-07 | Default Celery broker to SQLAlchemy/DB broker for native zero-docker Windows environment | Maintain strict No-Docker compliance while enabling async task queues |
| 2026-10-07 | Enforce PostgreSQL exclusively (no SQLite fallback) | Maintain strict production fidelity matching context.md Section 6 & 10 |
| 2026-10-08 | Implement uncertain detection tagging [0.25, conf_thresh) | Filter noise from inventory counts while retaining low-confidence tracks for review |
| 2026-10-08 | Use IoU > 0.30 union for empty facing and gap bounding box resolution | Avoid double-counting empty facings in multi-tier shelf planograms |
| 2026-10-08 | Deploy N_CONSISTENT (2-frame) StabilityFilter on shelf state transitions | Eliminate single-frame camera jitter and transient detection dropouts |
| 2026-10-08 | Implement QualityGate enforcing brightness [40, 230], Laplacian var >= 50, and max 60% identical pixels | Reject unusable frames and prevent spurious stockout alarms (status UNKNOWN) |
| 2026-10-08 | Enforce pre-save Gaussian anonymization on person bounding boxes | Comply strictly with non-negotiable retail privacy mandates (Section 9.1 & 15) |
| 2026-10-08 | Adopt high-buffer IoU tracker (30 frames) for static shelf items | Minimize identity switching (< 5% target) on static retail product packaging |
| 2026-10-08 | Implement two-tier removal verification (miss tolerance + 5-min put-back window) | Separate transient detection misses and customer put-backs from actual retail demand |
| 2026-10-08 | Derive demand_series directly from confirmed ITEM_REMOVED events | Feed clean empirical shelf removals into downstream time-series forecasting models |
| 2026-10-08 | Synthesize 200 days demand history with holidays & censored stockouts | Provide required training foundation for M7 forecasting without real POS dependence |
| 2026-10-08 | Establish Shelf-Demand Link matching inventory depletion to replay frames | Enable closed-loop visual simulation from stock depletion to supplier replenishment |
| 2026-10-08 | Separate repository into frontend/ (Next.js + TypeScript) and backend/ (FastAPI + PyTorch) | Clean decoupling of user interface from computer vision and async ingestion services |
| 2026-10-08 | Implement Milestone 6 Dashboard in Next.js React with glassmorphic dark theme and replay stepper | Deliver manager monitoring with live perception, planogram inspector, and HITL approval controls |
| 2026-10-08 | Train Multi-Quantile LSTM with SKU embeddings achieving 21.88% WAPE on fast movers | Beat 25.0% threshold and Moving Average baseline (26.50%), registered as Champion forecaster |
| 2026-10-08 | Implement deterministic Reorder Engine with MOQ, pack size ceiling, and capacity clamping | Ensure orders strictly cover lead time demand + safety stock while preventing duplicate open tickets |
| 2026-10-08 | Implement Agentic Layer with TicketStateMachine, guards, email dispatch, and scenarios S1-S7 | Strictly enforce approval gates, audit logging to agent_logs, and autonomous closed-loop refills |
