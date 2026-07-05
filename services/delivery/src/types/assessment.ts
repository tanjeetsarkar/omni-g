/**
 * V2 assessment domain types — mirror the Processor's Pydantic models defined
 * in docs/V2/DOMAIN-MODEL.md (Assessment, ConfidenceBand, CollectedEvidence,
 * CollectionGap).
 *
 * These types are used by:
 *   - useAssessmentEvents hook (real-time socket updates)
 *   - AssessmentPanel component (BLUF-first display)
 *   - /api/assessments route (REST proxy)
 */

export interface ConfidenceBand {
  /** Conservative lower bound (0.0–1.0) */
  low: number;
  /** Point estimate (0.0–1.0) */
  mid: number;
  /** Optimistic upper bound (0.0–1.0) */
  high: number;
}

export interface Assessment {
  /** "assessment--{uuid4}" */
  id: string;
  tenant_id: string;

  /** Which KIQ does this assess? */
  kiq_id: string;
  /** Leading hypothesis ID (null if no ACH ran) */
  hypothesis_id: string | null;

  /** BLUF: short declarative conclusion */
  conclusion: string;
  /** Probability band for confidence expression */
  confidence: ConfidenceBand;

  /** How the conclusion was reached */
  reasoning: string;
  /** Assumptions that had to hold */
  assumptions: string[];

  /** IDs of CollectedEvidence objects supporting the conclusion */
  supporting_evidence_ids: string[];
  /** IDs of CollectedEvidence objects contradicting the conclusion */
  contradicting_evidence_ids: string[];

  /** IDs of CollectionGap objects */
  collection_gaps: string[];
  /** Recommended analyst actions */
  recommended_next_actions: string[];

  /** DRAFT | READY | PUBLISHED | SUPERSEDED */
  status: string;
  /** PROCESSOR | ANALYST | HYBRID */
  produced_by: string;
  version: number;
  superseded_by_id: string | null;

  created: string;
  modified: string;
}

export interface AssessmentsResponse {
  assessments: Assessment[];
}
