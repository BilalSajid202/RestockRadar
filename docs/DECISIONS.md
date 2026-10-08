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
