# Omni-G V2 Domain Model

## Purpose

This document defines the records that V2 needs to support an intelligence-cycle workflow: planning around explicit questions, collecting evidence, testing competing hypotheses, and producing BLUF-first assessments.

The new records (KIQ, CollectedEvidence, Hypothesis, Assessment, CollectionGap) sit alongside the existing generic Entity and Relationship models. They are owned by different services and flow through the system as Kafka events or internal records.

## Core Records

### 1. Key Intelligence Question (KIQ)

**Owner:** Aggregator

**Purpose:** Define what the system is trying to answer, and drive all collection, processing, and dissemination against explicit tasking.

**Lifecycle:**
- Analyst creates a KIQ in Aggregator via HTTP API
- Aggregator publishes `kiq.created` event to Kafka
- Processor consumes and indexes the KIQ (for reference; processing does not modify KIQ state)
- Delivery displays active KIQs and surfaces assessments tied to each one

**Schema:**

```python
class KIQ(BaseModel):
    """Key Intelligence Question"""

    # Identity
    id: str  # "kiq--{uuid4}"
    tenant_id: str  # Multi-tenant isolation (required)

    # Question and framing
    question: str  # E.g., "What is the organizational structure of Acme Corp?"
    classification: str | None = None  # E.g., "UNCLASSIFIED//FOR OFFICIAL USE ONLY"
    description: str | None = None  # Longer explanation of why this question matters

    # Collection and refresh
    collection_focus: list[str] = Field(default_factory=list)  # E.g., ["news", "social_media", "government_records"]
    refresh_cadence_hours: int = 24  # How often to re-collect/re-assess
    max_age_days: int = 7  # Discard evidence older than this

    # Ownership and state
    owner_id: str  # Analyst who created the KIQ (user_id)
    status: str = "ACTIVE"  # ACTIVE, ARCHIVED, COMPLETED, ON_HOLD
    priority: int = 0  # For triage: higher = more urgent
    created: datetime
    modified: datetime

    # Version tracking
    version: int = 1  # For concurrent assessment updates
```

**Kafka Events:**
- `kiq.created` — new KIQ
- `kiq.updated` — KIQ policy or priority change
- `kiq.archived` — KIQ no longer active

**Storage:** KIQ records persist in a Postgres table (`kiq_questions`) and are indexed in the Processor for reference only. Processor does not modify KIQ state.

**Queries:**
- Aggregator: list active KIQs per tenant, update owner/priority/status
- Processor: fetch KIQ by ID for context during assessment
- Delivery: list active KIQs to display in left sidebar; link assessments to KIQs

---

### 2. CollectedEvidence

**Owner:** Processor (writes) / Aggregator (sources)

**Purpose:** Normalize and score evidence extracted from raw feeds. Each evidence object links a claim to a source, carries provenance metadata, and supports scoring for reliability and credibility.

**Parent Records:**
- Links to one KIQ (tasking context)
- Links to one Entity or Relationship (the claim)
- Links to one RawEvent (the source)

**Lifecycle:**
1. Aggregator publishes a `RawEvent` to Kafka with `source_id`, `plugin_id`, `plugin_version`, `tenant_id`, `kiq_id`
2. Processor validates, deduplicates, extracts entities/relationships
3. Processor creates CollectedEvidence objects for each extracted claim
4. Processor publishes `evidence.created` events to Kafka for Delivery visibility
5. Delivery receives event, hydrates graph, updates assessments

**Schema:**

```python
class SourceClassification(str, Enum):
    """Source discipline classification (Admiralty-style)"""
    HUMAN_INTELLIGENCE = "HUMINT"  # Informant, insider
    SIGNALS_INTELLIGENCE = "SIGINT"  # Intercepted communications
    IMAGERY_INTELLIGENCE = "IMINT"  # Photographs, satellite imagery
    OPEN_SOURCE_INTELLIGENCE = "OSINT"  # Public news, social media, government records
    MEASUREMENT_INTELLIGENCE = "MASINT"  # Sensors, analytics
    TECHNICAL_INTELLIGENCE = "TECHINT"  # Reverse engineering, signals analysis
    UNKNOWN = "UNKNOWN"


class ReliabilityRating(str, Enum):
    """Source reliability (A/B/C/D/E rating)"""
    ALWAYS_RELIABLE = "A"  # Always provides accurate information
    USUALLY_RELIABLE = "B"  # Usually provides accurate information
    FAIRLY_RELIABLE = "C"  # Occasionally provides inaccurate information
    UNRELIABLE = "D"  # Often provides inaccurate information
    ALWAYS_UNRELIABLE = "E"  # Always inaccurate
    UNKNOWN = "F"  # Reliability unknown


class CredibilityRating(str, Enum):
    """Information credibility (1-6 rating)"""
    CONFIRMED = "1"  # Confirmed by independent sources
    PROBABLY_TRUE = "2"  # Supported by independent sources
    POSSIBLY_TRUE = "3"  # Plausible but not independently supported
    DOUBTFUL = "4"  # Inconsistent with other information
    IMPROBABLE = "5"  # Inconsistent with known facts
    CANNOT_BE_JUDGED = "6"  # Cannot be evaluated


class CollectedEvidence(BaseModel):
    """Extracted and scored evidence from a raw feed"""

    # Identity
    id: str  # "evidence--{uuid4}"
    tenant_id: str  # Multi-tenant isolation (required)

    # Provenance
    kiq_id: str | None = None  # Optional: which KIQ motivated collection (may be untasked)
    source_event_id: str  # Reference to RawEvent in Kafka
    plugin_id: str  # Which MCP plugin or source provided this
    plugin_version: str | None = None

    # The claim
    entity_id: str | None = None  # If this is about a discovered entity
    relationship_id: str | None = None  # If this is about a discovered relationship
    assertion: str  # Human-readable summary: "Acme Corp is located in Delaware"

    # Sourcing details
    source_text: str  # Verbatim excerpt from source
    source_url: str | None = None  # Where this came from (link to article, post, etc.)
    source_timestamp: datetime  # When the source was published/captured

    # Source classification and reliability
    source_class: SourceClassification = SourceClassification.UNKNOWN  # HUMINT, OSINT, etc.
    source_reliability: ReliabilityRating = ReliabilityRating.UNKNOWN  # A–F rating
    information_credibility: CredibilityRating = CredibilityRating.CANNOT_BE_JUDGED  # 1–6 rating

    # Confidence in extraction
    extraction_confidence: float = Field(default=0.5, ge=0.0, le=1.0)  # Did the LLM extract correctly?

    # Application state
    status: str = "NEW"  # NEW, CONFIRMED, DISPUTED, SUPERSEDED
    tags: list[str] = Field(default_factory=list)  # ["important", "suspicious", "corroborated"]
    created: datetime
    modified: datetime
```

**Kafka Events:**
- `evidence.created` — new evidence published to graph
- `evidence.credibility_updated` — analyst or background process re-rated the evidence
- `evidence.disputed` — analyst marked evidence as inconsistent with other data

**Storage:** CollectedEvidence records persist in Neo4j as relationships:
- Pattern: `(Entity) -[:EVIDENCE]-> (EvidenceNode {id, assertion, source_reliability, credibility, ...})`
- Or in a separate Postgres table for historical querying and scoring

**Queries:**
- Processor: create evidence for each extracted entity/relationship
- Processor: query evidence supporting a hypothesis (for ACH)
- Processor: query evidence contradicting a hypothesis
- Delivery: list evidence for a KIQ, sorted by recency and credibility
- Delivery: filter evidence by source class, reliability, credibility

---

### 3. Hypothesis

**Owner:** Processor

**Purpose:** Represent a candidate explanation or theory about a KIQ. Hypotheses support Analysis of Competing Hypotheses (ACH) workflows so the system can test multiple explanations before committing to an assessment.

**Parent Records:**
- Links to one KIQ (what question does this hypothesis answer?)
- Links to many CollectedEvidence objects (supporting and contradicting)

**Lifecycle:**
1. Processor receives a KIQ and new evidence
2. Processor generates one or more plausible hypotheses via LLM
3. For each hypothesis, Processor queries existing evidence for support and contradiction
4. Processor publishes `hypothesis.generated` event
5. Processor runs background ACH scoring to compare hypotheses
6. When one hypothesis dominates, it feeds into Assessment generation

**Schema:**

```python
class Hypothesis(BaseModel):
    """Candidate explanation for a KIQ"""

    # Identity
    id: str  # "hypothesis--{uuid4}"
    tenant_id: str  # Multi-tenant isolation (required)

    # Context
    kiq_id: str  # Which KIQ does this explain?

    # The hypothesis
    statement: str  # E.g., "Acme Corp is planning to acquire Retail Inc."
    reasoning: str  # Why this is plausible

    # ACH scoring
    likelihood_ratio: float | None = None  # H / ~H for use in Bayesian updates
    supporting_evidence_ids: list[str] = Field(default_factory=list)  # CollectedEvidence IDs that support
    contradicting_evidence_ids: list[str] = Field(default_factory=list)  # CollectedEvidence IDs that contradict

    # Status and lifecycle
    status: str = "CANDIDATE"  # CANDIDATE, PLAUSIBLE, PROBABLE, LEADING, REJECTED
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)  # Current belief in this hypothesis
    generated_by: str = "LLM"  # How was this generated? (LLM, ANALYST, ACH)
    analyst_notes: str | None = None

    created: datetime
    modified: datetime
```

**Kafka Events:**
- `hypothesis.generated` — new candidate hypothesis
- `hypothesis.scored` — ACH scoring updated hypothesis ranking
- `hypothesis.rejected` — hypothesis was ruled out

**Storage:** Hypothesis records persist in Neo4j or Postgres. Link via relationships:
- Pattern: `(KIQ) -[:HAS_HYPOTHESIS]-> (HypothesisNode {id, statement, status, confidence, ...})`

**Queries:**
- Processor: generate hypotheses for a KIQ
- Processor: score hypotheses against evidence (ACH)
- Processor: list hypotheses for a KIQ ranked by confidence
- Delivery: show competing hypotheses to analyst for a KIQ
- Delivery: allow analyst to manually score or reject hypotheses

---

### 4. Assessment

**Owner:** Processor (produces) / Delivery (displays)

**Purpose:** Final analyst-grade output: a BLUF (Bottom Line Up Front) conclusion tied to a KIQ, with confidence band, supporting evidence, contradictory evidence, and explicit intelligence gaps.

**Parent Records:**
- Links to one KIQ (what was the question?)
- Links to many CollectedEvidence objects (support and contradiction)
- Links to one Hypothesis (which hypothesis won ACH?)
- Links to many CollectionGap objects (what do we still need to know?)

**Lifecycle:**
1. Processor has evidence and hypotheses for a KIQ
2. Processor runs ACH or analyst selects a leading hypothesis
3. Processor produces an Assessment object with BLUF, confidence band, reasoning
4. Processor publishes `assessment.produced` event to Kafka
5. Delivery receives event, highlights BLUF in UI
6. Analyst can drill down into evidence, gaps, and contradictions

**Schema:**

```python
class ConfidenceBand(BaseModel):
    """Probability band for confidence expression"""
    low: float = Field(ge=0.0, le=1.0)  # Lower bound
    mid: float = Field(ge=0.0, le=1.0)  # Point estimate
    high: float = Field(ge=0.0, le=1.0)  # Upper bound


class Assessment(BaseModel):
    """Final analyst-grade assessment for a KIQ"""

    # Identity
    id: str  # "assessment--{uuid4}"
    tenant_id: str  # Multi-tenant isolation (required)

    # Context
    kiq_id: str  # Which KIQ does this assess?
    hypothesis_id: str | None = None  # Which hypothesis won?

    # BLUF (Bottom Line Up Front)
    conclusion: str  # Short, declarative statement: "Acme Corp is planning to acquire Retail Inc."
    confidence: ConfidenceBand  # Probability band: low 0.3, mid 0.6, high 0.8

    # Reasoning and evidence
    reasoning: str  # Explanation of how we reached this conclusion
    assumptions: list[str] = Field(default_factory=list)  # What had to be true for this to hold
    supporting_evidence_ids: list[str] = Field(default_factory=list)  # Strongest CollectedEvidence
    contradicting_evidence_ids: list[str] = Field(default_factory=list)  # Evidence against conclusion

    # Intelligence gaps and next steps
    collection_gaps: list[str] = Field(default_factory=list)  # IDs of CollectionGap objects
    recommended_next_actions: list[str] = Field(default_factory=list)
    # E.g., ["Collect Acme's financial filings", "Interview Retail board members"]

    # Status and validity
    status: str = "DRAFT"  # DRAFT, READY, PUBLISHED, SUPERSEDED
    produced_by: str = "PROCESSOR"  # Who/what generated this? (PROCESSOR, ANALYST, HYBRID)

    # Versioning for updates
    version: int = 1
    superseded_by_id: str | None = None  # If a new assessment replaces this

    created: datetime
    modified: datetime
```

**Kafka Events:**
- `assessment.produced` — new assessment published
- `assessment.updated` — assessment confidence or evidence changed
- `assessment.superseded` — new assessment replaces an old one

**Storage:** Assessment records persist in Neo4j or Postgres. Relationships:
- Pattern: `(Assessment) -[:ANSWERS]-> (KIQ)`
- Pattern: `(Assessment) -[:SUPPORTS]-> (CollectedEvidence)`
- Pattern: `(Assessment) -[:CONTRADICTED_BY]-> (CollectedEvidence)`

**Queries:**
- Processor: produce assessment for a KIQ
- Processor: update assessment when new evidence arrives
- Delivery: list assessments for active KIQs
- Delivery: show assessment BLUF, evidence, gaps for analyst review
- Delivery: allow analyst to provide feedback or request re-analysis

---

### 5. CollectionGap

**Owner:** Processor

**Purpose:** Explicit documentation of what the system does not know but needs to know to answer the KIQ with higher confidence.

**Parent Records:**
- Links to one KIQ (what question does this gap relate to?)
- Linked from many Assessment objects

**Lifecycle:**
1. Processor generates an Assessment
2. During ACH or confidence scoring, Processor identifies missing information
3. Processor creates CollectionGap objects for each gap
4. Processor publishes gaps with assessment
5. Delivery displays gaps to analyst
6. Analyst can approve a gap as a tasking directive (back to Aggregator)

**Schema:**

```python
class CollectionGap(BaseModel):
    """Explicit documentation of missing information"""

    # Identity
    id: str  # "gap--{uuid4}"
    tenant_id: str  # Multi-tenant isolation (required)

    # Context
    kiq_id: str  # Which KIQ does this gap relate to?
    assessment_id: str | None = None  # Which assessment identified this gap?

    # The gap
    gap_statement: str  # E.g., "Current financial status of Retail Inc. (FY 2025)"
    why_needed: str  # Why does the analyst need this? E.g., "To assess acquisition financing likelihood"

    # Collection guidance
    suggested_sources: list[str] = Field(default_factory=list)  # E.g., ["SEC filings", "press releases"]
    suggested_plugins: list[str] = Field(default_factory=list)  # E.g., ["reuters", "newsrss"]
    collection_priority: int = 0  # Triage: higher = more urgent

    # Status and tasking
    status: str = "IDENTIFIED"  # IDENTIFIED, TASKED, IN_PROGRESS, FILLED, INVALIDATED
    tasking_issued: bool = False  # Has this been tasked back to Aggregator?

    created: datetime
    modified: datetime
```

**Kafka Events:**
- `gap.identified` — new gap found during assessment
- `gap.tasked` — analyst or system tasked collection to fill the gap
- `gap.filled` — new evidence addressed the gap

**Storage:** CollectionGap records persist in Neo4j or Postgres. Relationships:
- Pattern: `(Gap) -[:RELATES_TO]-> (KIQ)`
- Pattern: `(Gap) -[:ADDRESSED_BY]-> (CollectedEvidence)`

**Queries:**
- Processor: identify gaps during assessment generation
- Processor: mark gap as filled when new evidence arrives
- Delivery: list gaps for a KIQ; allow analyst to task collection
- Aggregator: receive gap tasking and add to collection policy

---

## Relationship to Existing Entity and Relationship Models

The new records (KIQ, CollectedEvidence, Hypothesis, Assessment, CollectionGap) are **independent** of the existing generic Entity and Relationship models. They coexist in the graph but serve different purposes:

### Existing Models (Unchanged)

**Entity:**
```
{
  id: str,
  type: str,  # LLM-determined: "Person", "Organization", "Event", etc.
  name: str,
  description: str | None,
  properties: dict,  # Domain-specific attributes
  confidence: float,  # Extraction confidence (0.0–1.0)
  tenant_id: str,
  source_id: str | None,  # Plugin/source that provided this
  source_spans: list[EvidenceSpan],  # Grounding in raw text
  created: datetime,
  modified: datetime,
}
```

**Relationship:**
```
{
  id: str,
  type: str,  # LLM-determined: "KNOWS", "LOCATED_AT", "PARTICIPATED_IN", etc.
  source_ref: str,  # Entity ID
  target_ref: str,  # Entity ID
  confidence: float,  # Extraction confidence (0.0–1.0)
  tenant_id: str,
  created: datetime,
  modified: datetime,
}
```

**Purpose:** Entity and Relationship capture *what was extracted* from raw feeds, without interpretation. They are the raw building blocks of the knowledge graph.

### New Models (V2-Specific)

**CollectedEvidence:**
- Wraps an Entity or Relationship with *tasking context* (KIQ), *source classification*, *reliability/credibility scoring*, and *analyst interpretation*.
- Example: An extracted Entity "Acme Corp" becomes evidence "Acme Corp exists and operates in Delaware" with Admiralty-style reliability and credibility ratings.

**Hypothesis:**
- Connects multiple CollectedEvidence objects with a claim about the KIQ.
- Example: "Acme Corp is planning to acquire Retail Inc." supported by evidence like "Acme acquired three retail companies in the past two years" and "Retail Inc. stock price dropped 15% after Acme's CEO mentioned consolidation."

**Assessment:**
- Wraps a Hypothesis with final confidence, explicit gaps, and recommended next actions.
- Example: "BLUF: Acme Corp is probably planning to acquire Retail Inc. Confidence: 60%. Supporting: [evidence IDs]. Contradicting: [evidence IDs]. Gaps: [gap IDs]. Next: Collect Acme financial statements."

**CollectionGap:**
- Identifies missing information needed to raise confidence or resolve contradictions.
- Example: "Acme's current cash position" is unknown but needed to assess acquisition financing.

### Graph Schema

In Neo4j, the two model families coexist as separate node types and relationships:

**Entity and Relationship nodes:**
```cypher
(:Entity:{TypeLabel}:{tenant_label} { id, type, name, confidence, ... })
(:Entity)-[:{RelationshipType}]->(Entity)
```

**V2 Intelligence-cycle nodes:**
```cypher
(:KIQ:{tenant_label} { id, question, status, ... })
(:CollectedEvidence { id, assertion, source_reliability, credibility, ... })
(:Hypothesis { id, statement, confidence, ... })
(:Assessment { id, conclusion, confidence_band, ... })
(:CollectionGap { id, gap_statement, status, ... })

# Relationships between them
(KIQ) -[:HAS_EVIDENCE]-> (CollectedEvidence)
(Hypothesis) -[:SUPPORTS]-> (CollectedEvidence)  # Or references by ID
(Assessment) -[:ANSWERS]-> (KIQ)
(Assessment) -[:BASED_ON]-> (Hypothesis)
(Assessment) -[:HAS_GAP]-> (CollectionGap)

# Bridge to Entity/Relationship
(CollectedEvidence) -[:ABOUT_ENTITY]-> (Entity)
(CollectedEvidence) -[:ABOUT_RELATIONSHIP]-> (Relationship)  # Not a Neo4j edge; use IDs or separate query
```

### Data Flow

```
1. Aggregator publishes RawEvent to Kafka (with source_id, plugin_id, kiq_id, tenant_id)
   ↓
2. Processor consumes RawEvent
   ↓
3. Processor extracts Entity and Relationship objects
   ↓
4. Processor creates CollectedEvidence objects (wrapping Entity/Relationship with KIQ and source classification)
   ↓
5. Processor generates Hypothesis objects (bundling CollectedEvidence into theories)
   ↓
6. Processor runs ACH and scores Hypothesis objects
   ↓
7. Processor creates Assessment object (final BLUF + gaps)
   ↓
8. Processor creates CollectionGap objects (what we don't know)
   ↓
9. Processor publishes assessment.produced event to Kafka
   ↓
10. Delivery receives event and displays Assessment (BLUF first, then supporting evidence, gaps, contradictions)
```

## Service Ownership Summary

| Record | Owner | Creates | Modifies | Queries | Storage |
|--------|-------|---------|----------|---------|---------|
| KIQ | Aggregator | Analyst → Aggregator API | Aggregator (status, priority) | Aggregator, Processor, Delivery | Postgres `kiq_questions` table |
| CollectedEvidence | Processor | Processor (from RawEvent + extraction) | Processor (credibility updates), Analyst (via Delivery API) | Processor, Delivery, (Aggregator for gap tasking) | Neo4j or Postgres |
| Hypothesis | Processor | Processor (LLM generation) | Processor (ACH scoring) | Processor, Delivery | Neo4j or Postgres |
| Assessment | Processor | Processor (from leading hypothesis) | Processor (on new evidence), Analyst (override) | Processor, Delivery | Neo4j or Postgres |
| CollectionGap | Processor | Processor (during assessment) | Processor (status on new evidence), Aggregator (tasking) | Processor, Delivery, Aggregator | Neo4j or Postgres |

## Validation and Schema Enforcement

All V2 records must comply with:

1. **Tenant isolation (required):** Every record carries `tenant_id` and queries must filter by it.
2. **Provenance:** KIQ and CollectedEvidence carry `source_id` or `owner_id` to track origin.
3. **Timestamps:** All records have `created` and `modified` for audit trails.
4. **Idempotency:** `id` is stable across republication; Kafka consumers should use UPSERT semantics.
5. **Confidence bands:** Confidence always 0.0–1.0; Assessment uses a ConfidenceBand object for richer expression.

Pydantic models will enforce these at the service boundary (Processor ingestion edge, Aggregator API validation sidecar).

## Implementation Phases

### Phase 1 (Immediate): Domain Model + Kafka Schema
- [ ] Add KIQ, CollectedEvidence, Hypothesis, Assessment, CollectionGap Pydantic models to Processor
- [ ] Add Kafka topic definitions for `kiq.created`, `evidence.created`, `hypothesis.generated`, `assessment.produced`, `gap.identified`
- [ ] Update Aggregator to accept KIQ creation via HTTP API
- [ ] Aggregator publishes `kiq.created` events to Kafka

### Phase 2: Evidence Binding
- [ ] Processor creates CollectedEvidence objects for each extracted Entity/Relationship
- [ ] Processor publishes `evidence.created` events
- [ ] Delivery consumes evidence events and updates graph UI

### Phase 3: Hypothesis Generation
- [ ] Processor generates Hypothesis objects from evidence via LLM prompting
- [ ] Processor implements Analysis of Competing Hypotheses (ACH) scoring

### Phase 4: Assessment Production
- [ ] Processor produces Assessment objects with BLUF, confidence band, and gaps
- [ ] Delivery displays Assessment BLUF-first

### Phase 5: Gap Tasking
- [ ] CollectionGap records direct back to Aggregator for new tasking
- [ ] Aggregator updates collection policies based on gaps

---

## Glossary

| Term | Definition |
|------|-----------|
| **BLUF** | Bottom Line Up Front: a concise, declarative conclusion delivered before supporting details |
| **ACH** | Analysis of Competing Hypotheses: systematic comparison of alternative explanations using evidence |
| **Admiralty Scale** | Source reliability and information credibility rating system (A–F and 1–6) |
| **KIQ** | Key Intelligence Question: explicit tasking directive that drives collection and analysis |
| **CollectedEvidence** | Extracted claim normalized with source classification and credibility scoring |
| **Hypothesis** | Candidate explanation for a KIQ supported by CollectedEvidence |
| **Assessment** | Final analyst-grade output: BLUF + confidence band + evidence + gaps |
| **CollectionGap** | Explicit missing information needed to raise confidence or resolve contradictions |
| **Grounding** | Verification that extracted entities appear in raw source text (prevents LLM hallucination) |
| **Tenant Isolation** | Data partition ensuring one tenant cannot query or modify another tenant's records |
| **Provenance** | Metadata tracking origin, source classification, and reliability of information |
