# Omni-G V2 Overhaul

This directory is the working source of truth for the overhaul aligned to `overhaul.md`.

## V2 Documents

- `ARCHITECTURE.md` — target application and service architecture
- `ROADMAP.md` — phased execution roadmap for the overhaul
- `INFRASTRUCTURE-TRANSITION.md` — runtime, orchestration, and infrastructure migration plan

## Design Baseline

V2 keeps the current three-service split:

- Aggregator — planning/tasking intake plus collection orchestration
- Processor — intelligence pipeline and analytical engine
- Delivery — dissemination, graph exploration, and analyst feedback

V2 also keeps Kafka as the ingestion backbone and introduces Celery behind the Processor consumer for orchestration.
