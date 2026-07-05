# Omni-G V2 Roadmap

## Purpose

This roadmap replaces the greenfield-style milestone sequence with a migration plan from the current V1 system to the V2 intelligence-cycle architecture.

## Guiding Outcome

By the end of V2, Omni-G should:

- collect evidence against explicit KIQs
- score source reliability and information credibility
- test multiple competing hypotheses before issuing an assessment
- deliver BLUF-first outputs with confidence, intelligence gaps, and next actions
- run Processor analysis through Celery orchestration instead of inline consumer-bound tasking

## Workstreams

- Workstream A — documentation restructuring and architecture source-of-truth
- Workstream B — Processor orchestration and Celery migration
- Workstream C — domain model and analytical workflow changes
- Workstream D — Delivery dissemination redesign
- Workstream E — infrastructure and observability transition

## Phase 0: Archive and Reset the Documentation Baseline

Status: in progress

Deliverables:

- Create `docs/V1/` with archived pre-overhaul documentation.
- Create `docs/V2/` with target-state architecture and roadmap documents.
- Add a top-level docs index that points readers to the correct track.
- Update the gap matrix to track V2 migration items.

Acceptance criteria:

- Historical architecture and roadmap documents are accessible from `docs/V1/`.
- V2 documents are the explicit planning target for new work.
- The repo has one visible place to track migration deltas.

## Phase 1: Reframe the Application Around KIQ-Driven Workflow

Primary workstreams: A, C

Deliverables:

- Define the KIQ lifecycle and ownership model.
- Define source classes and evidence metadata requirements.
- Define the new assessment objects: hypothesis, assessment, collection gap.
- Specify how KIQ and source metadata flow from Aggregator into Processor and Delivery.

Acceptance criteria:

- A V2 domain model exists for KIQ, evidence, hypothesis, assessment, and gap records.
- Every intelligence-cycle stage maps to a concrete service boundary.
- The planned event schema is explicit enough to implement without reopening architecture.

## Phase 2: Introduce Celery Behind the Processor Consumer

Primary workstreams: B, E

Deliverables:

- Add Celery broker/result configuration to the Processor runtime.
- Keep the current Kafka consumer and DLQ model.
- Queue one coarse `process_event` task per consumed event.
- Move briefing scheduling to Celery Beat.
- Define queue names, retries, idempotency, and failure handling.

Acceptance criteria:

- The Processor no longer performs the main pipeline inline inside the Kafka consumer loop.
- A failed task can retry without destabilizing Kafka intake.
- The low-resource local path remains documented and runnable.

## Phase 3: Add Source Evaluation and Evidence Scoring

Primary workstreams: B, C

Deliverables:

- Add source reliability and information credibility fields.
- Introduce an Admiralty-style mapping for analyst-facing output.
- Ensure extracted evidence carries source spans and provenance.
- Store enough evidence metadata to compare support and contradiction across hypotheses.

Acceptance criteria:

- Evidence objects can be ranked and filtered by reliability and credibility.
- Delivery can display source evaluation clearly.
- Processor can use evidence scoring as an input to assessment generation.

## Phase 4: Add Hypothesis Testing and Assessment Production

Primary workstreams: B, C, D

Deliverables:

- Introduce hypothesis generation per KIQ.
- Implement an Analysis of Competing Hypotheses workflow.
- Produce a stable assessment model with BLUF, confidence band, supporting evidence, contradictory evidence, and intelligence gaps.
- Publish assessments and status events for Delivery consumption.

Acceptance criteria:

- Processor can produce more than one plausible explanation for a KIQ.
- Assessments explicitly show what supports and what weakens the conclusion.
- Confidence output is bounded and reviewable instead of opaque.

## Phase 5: Redesign Dissemination in Delivery

Primary workstreams: D

Deliverables:

- Add BLUF-first assessment views.
- Show intelligence gaps and next collection recommendations.
- Keep search-first graph exploration as a supporting mode rather than the only mode.
- Tie real-time alerts to KIQs, assessments, and active evidence updates.

Acceptance criteria:

- A user can answer "what is the conclusion?" before reading the full graph.
- A user can see what the system does not know.
- A user can trace each assessment back to evidence and source evaluation.

## Phase 6: Simplify, Harden, and Remove V1 Carryovers

Primary workstreams: A, B, D, E

Deliverables:

- Remove or demote V1 workflows that are not KIQ-driven.
- Move non-essential hot-path enrichment fully into background tasks.
- Update observability to cover Celery queue health and assessment throughput.
- Document the supported production and local development topologies.

Acceptance criteria:

- Remaining hot-path work is justified by the V2 workflow.
- Queue, worker, and event health are observable.
- Documentation no longer describes the V1 system as the target architecture.

## Immediate Execution Order

1. Finalize V1/V2 doc structure.
2. Write the V2 infrastructure transition specification.
3. Add Processor runtime design notes for Kafka-to-Celery migration.
4. Define the KIQ and assessment domain models.
5. Begin Processor orchestration implementation.

## Incremental Implementation Playbook

Use this section as the working sequence for driving Copilot agents incrementally. Each step is intentionally narrow so you can ask for one thing at a time, run it, and fix issues before moving forward.

### Working Rule

For each step:

1. Ask Copilot to change only the named slice.
2. Run the listed verification yourself immediately after the change.
3. If the check fails, fix that same slice before asking for the next step.
4. Update `docs/agent-contexts/gap-matrix.md` whenever behavior or implementation status changes.

### Step 0: Keep the Documentation Surface Stable

Goal:

- Finish any remaining V1/V2 documentation cleanup before runtime changes expand scope.

Ask Copilot:

```text
Update the V2 docs only for [specific topic]. Do not change runtime code. Also update docs/agent-contexts/gap-matrix.md if the planning status changes.
```

You verify:

- `git diff -- docs/ .github/copilot-instructions.md`
- Confirm the V2 docs still match the intended architecture direction.

Done when:

- V2 planning docs are clear enough to implement without reopening architecture questions.

### Step 1: Add the V2 Domain Contract Before Runtime Changes

Goal:

- Define the records V2 needs before changing Processor flow.

Ask Copilot:

```text
Create or update a V2 domain-model design doc that defines KIQ, CollectedEvidence, Hypothesis, Assessment, and CollectionGap, including which service owns each record and how they relate to the existing Entity and Relationship models.
```

You verify:

- Read the resulting document and check that every new record has:
	- owner service
	- required fields
	- tenant and provenance requirements
	- relation to Kafka events or APIs

Done when:

- The KIQ and assessment model is specific enough that Aggregator, Processor, and Delivery changes can be implemented against it.

### Step 2: Introduce Celery Configuration Without Replacing the Current Pipeline

Goal:

- Add the orchestration scaffolding first, without changing the data model and pipeline semantics at the same time.

Ask Copilot:

```text
Add the minimum Celery runtime scaffolding for the Processor so the current Kafka consumer can dispatch one coarse process_event task. Keep the current pipeline logic intact. Update Docker and config surfaces only as needed for this slice.
```

You verify:

- Run the narrowest Processor checks available.
- Expected minimum checks:
	- Processor tests touching config, startup, or pipeline entry
	- local type/lint checks for Processor
	- compose/config validation if docker files changed

Suggested commands if still applicable in this repo:

```text
Run Processor unit tests for the touched slice.
Run Processor lint/type checks for the touched slice.
Validate docker compose if runtime files changed.
```

Done when:

- The Processor can be configured for Celery-backed execution without breaking current ingestion behavior.

### Step 3: Switch the Processor Consumer to Dispatch Coarse Tasks

Goal:

- Move the heavy execution path out of the Kafka consumer loop while preserving the current pipeline behavior.

Ask Copilot:

```text
Change the Processor so the Kafka consumer dispatches one coarse Celery task per consumed event instead of running the full pipeline inline. Keep existing DLQ and pipeline semantics as stable as possible.
```

You verify:

- Run Processor tests around consumer and pipeline flow.
- Run any startup/runtime validation available for the Processor.
- Confirm the change still respects the V2 direction in docs.

Done when:

- Kafka intake remains lightweight and the current pipeline is still reachable through queued execution.

### Step 4: Move Scheduled Analytical Work Toward Celery Beat

Goal:

- Remove scheduling drift before adding new V2 analytical features.

Ask Copilot:

```text
Refactor Processor scheduling surfaces so briefing and other recurring analytical jobs are prepared to run through Celery Beat rather than ad hoc in-process schedulers. Keep the change incremental.
```

You verify:

- Run the relevant briefing and scheduler tests.
- Confirm there is one clear scheduling model instead of split mechanisms.

Done when:

- Scheduled analytical jobs no longer depend on long-term APScheduler-style ownership.

### Step 5: Add KIQ Metadata to Aggregator and Processor Contracts

Goal:

- Make collection task-driven before adding richer analysis.

Ask Copilot:

```text
Add the smallest viable KIQ metadata path from Aggregator into the Processor event envelope. Do not implement the full KIQ product yet; just make the contract explicit and preserved end to end.
```

You verify:

- Run Aggregator tests for request and event shapes.
- Run Processor tests for envelope validation and propagation.
- Confirm untasked events are either explicitly allowed or explicitly marked.

Done when:

- Raw events can be traced to a KIQ or to a clearly declared untasked path.

### Step 6: Add Evidence Records and Source Scoring

Goal:

- Introduce the minimum evidence model needed for V2 assessments.

Ask Copilot:

```text
Implement the first slice of V2 evidence handling: add source-class metadata, reliability and credibility fields, and preserve source-span/provenance in Processor outputs without attempting the full assessment workflow yet.
```

You verify:

- Run Processor model, extraction, and pipeline tests.
- Inspect sample outputs or fixtures to confirm the evidence fields are present and coherent.

Done when:

- Processor output can support later assessment work with real evidence quality signals.

### Step 7: Implement the First Assessment Slice

Goal:

- Produce one bounded V2 outcome before implementing the full analytical system.

Ask Copilot:

```text
Implement a first-pass assessment object for one KIQ flow: BLUF, confidence band, supporting evidence, contradictory evidence, and intelligence gaps. Keep the implementation simple and traceable.
```

You verify:

- Run Processor tests for the new assessment logic.
- Inspect generated assessment payloads manually.
- Confirm the output is explainable and evidence-backed.

Done when:

- The system can produce a minimal V2 assessment rather than only graph or alert artifacts.

### Step 8: Add the First Delivery Assessment View

Goal:

- Make the new V2 output visible to users before broad UI redesign.

Ask Copilot:

```text
Add the smallest Delivery UI slice that displays a BLUF-first assessment with confidence, evidence summary, and intelligence gaps. Keep the existing graph UX intact and treat it as supporting context.
```

You verify:

- Run Delivery tests for the touched slice.
- Run the local UI and confirm a user can see the conclusion before exploring the graph.

Done when:

- Delivery has one real V2 dissemination surface.

### Step 9: Add Competing Hypotheses and Background Reanalysis

Goal:

- Increase analytical rigor after the first assessment flow works end to end.

Ask Copilot:

```text
Implement the next V2 analytical slice: support multiple hypotheses for a KIQ and prepare background reassessment through Celery-driven jobs. Keep the change incremental and testable.
```

You verify:

- Run Processor analytical tests.
- Check that more than one hypothesis can exist for the same KIQ.
- Confirm reassessment is background-oriented, not hot-path blocking.

Done when:

- Major assessments are no longer based on a single unexplained conclusion.

### Step 10: Simplify V1 Carryovers

Goal:

- Remove or demote legacy flows only after a usable V2 path exists.

Ask Copilot:

```text
Identify and remove or demote V1 behaviors that conflict with the V2 KIQ-driven workflow, but only where there is already a working V2 replacement. Update docs and gap-matrix entries accordingly.
```

You verify:

- Run the narrow tests for the touched slice.
- Confirm no required V1 fallback was removed prematurely.

Done when:

- The codebase defaults toward V2 behavior rather than carrying legacy assumptions in the hot path.

## Suggested Agent Prompts by Workstream

### Documentation and Architecture

Use when you want planning-only updates.

```text
Update only the V2 documentation for [topic]. Do not change runtime code. Keep the content aligned with docs/V2/ARCHITECTURE.md and docs/V2/ROADMAP.md, and update docs/agent-contexts/gap-matrix.md if implementation status or migration status changes.
```

### Processor Orchestration

Use when changing Kafka, Celery, scheduling, or pipeline execution.

```text
Implement only the next incremental Processor orchestration slice for V2. Keep Kafka as the intake boundary, preserve current behavior where possible, and avoid widening into KIQ or UI changes unless required for this slice. Run the narrowest relevant validation after editing.
```

### Aggregator and KIQ Contract

Use when changing tasking, collection metadata, or envelope ownership.

```text
Implement only the next Aggregator-side V2 contract slice for KIQ-driven collection. Keep plugin orchestration generic, preserve schema validation discipline, and limit changes to the minimum contract needed for the selected step.
```

### Delivery Dissemination

Use when changing assessment presentation or graph-to-assessment balance.

```text
Implement only the next Delivery-side V2 dissemination slice. Keep graph exploration intact, but make the new BLUF-first assessment output visible. Do not redesign unrelated UI surfaces.
```

## Definition of Done Per Increment

Do not start the next step until the current one satisfies all of these:

1. The slice is small enough to explain in one paragraph.
2. The touched service has been validated with the narrowest relevant tests or checks.
3. `docs/agent-contexts/gap-matrix.md` reflects the new implementation state.
4. Any V2 doc drift introduced by the change has been corrected.
5. There is a clear rollback path if the next slice fails.
