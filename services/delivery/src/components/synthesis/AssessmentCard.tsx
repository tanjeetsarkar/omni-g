"use client";

/**
 * AssessmentCard — renders a BLUF (Bottom Line Up Front) assessment
 * with confidence score, supporting/contradicting evidence counts,
 * and collection gaps.
 *
 * V2 Domain Model: Assessment
 *   - BLUF statement (summary)
 *   - confidence (0.0–1.0)
 *   - supporting_evidence_ids / contradicting_evidence_ids
 *   - collection_gaps → CollectionGap[]
 *   - recommended_next_actions
 */

import { useState } from "react";
import type { Assessment } from "@/types/entities";

interface AssessmentCardProps {
  assessment: Assessment;
  onEvidenceClick?: (evidenceId: string) => void;
  onGapClick?: (gapId: string) => void;
}

function confidenceColor(score: number): string {
  if (score >= 0.8) return "text-green-600 dark:text-green-400";
  if (score >= 0.5) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function confidenceBg(score: number): string {
  if (score >= 0.8) return "bg-green-50 dark:bg-green-900/20";
  if (score >= 0.5) return "bg-yellow-50 dark:bg-yellow-900/20";
  return "bg-red-50 dark:bg-red-900/20";
}

export function AssessmentCard({
  assessment,
  onEvidenceClick,
  onGapClick,
}: AssessmentCardProps) {
  const [expanded, setExpanded] = useState(false);

  const confidencePct = Math.round(assessment.confidence * 100);

  return (
    <div
      className={`rounded-lg border p-4 shadow-sm transition-colors ${confidenceBg(assessment.confidence)}`}
    >
      {/* Header: BLUF + Confidence */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
              BLUF Assessment
            </span>
            {assessment.kiq_id && (
              <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">
                KIQ:{assessment.kiq_id.slice(0, 8)}
              </span>
            )}
          </div>
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-relaxed">
            {assessment.summary}
          </p>
        </div>

        {/* Confidence badge */}
        <div
          className={`flex-shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold ${confidenceColor(assessment.confidence)} ${confidenceBg(assessment.confidence)}`}
        >
          <svg
            className="w-3.5 h-3.5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d={
                assessment.confidence >= 0.8
                  ? "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                  : assessment.confidence >= 0.5
                    ? "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
                    : "M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
              }
            />
          </svg>
          {confidencePct}%
        </div>
      </div>

      {/* Evidence counts */}
      <div className="flex items-center gap-4 mt-3 text-xs text-gray-500 dark:text-gray-400">
        <span className="flex items-center gap-1">
          <svg
            className="w-3.5 h-3.5 text-green-500"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clipRule="evenodd"
            />
          </svg>
          {assessment.supporting_evidence_ids?.length ?? 0} supporting
        </span>
        <span className="flex items-center gap-1">
          <svg
            className="w-3.5 h-3.5 text-red-500"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clipRule="evenodd"
            />
          </svg>
          {assessment.contradicting_evidence_ids?.length ?? 0} contradicting
        </span>
        {assessment.collection_gaps &&
          assessment.collection_gaps.length > 0 && (
            <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
              <svg
                className="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              {assessment.collection_gaps.length} gap
              {assessment.collection_gaps.length > 1 ? "s" : ""}
            </span>
          )}
      </div>

      {/* Expand for details */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="mt-2 text-xs text-blue-600 dark:text-blue-400 hover:underline focus:outline-none"
      >
        {expanded ? "Show less" : "Show details"}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-gray-200 dark:border-gray-700 pt-3">
          {/* Supporting evidence */}
          {assessment.supporting_evidence_ids &&
            assessment.supporting_evidence_ids.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Supporting Evidence
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {assessment.supporting_evidence_ids.map((id) => (
                    <button
                      key={id}
                      onClick={() => onEvidenceClick?.(id)}
                      className="text-xs px-2 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-900/50 transition-colors font-mono"
                    >
                      {id.slice(0, 8)}…
                    </button>
                  ))}
                </div>
              </div>
            )}

          {/* Contradicting evidence */}
          {assessment.contradicting_evidence_ids &&
            assessment.contradicting_evidence_ids.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Contradicting Evidence
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {assessment.contradicting_evidence_ids.map((id) => (
                    <button
                      key={id}
                      onClick={() => onEvidenceClick?.(id)}
                      className="text-xs px-2 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors font-mono"
                    >
                      {id.slice(0, 8)}…
                    </button>
                  ))}
                </div>
              </div>
            )}

          {/* Collection gaps */}
          {assessment.collection_gaps &&
            assessment.collection_gaps.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Collection Gaps
                </h4>
                <div className="space-y-1.5">
                  {assessment.collection_gaps.map((gap) => (
                    <button
                      key={gap.gap_id}
                      onClick={() => onGapClick?.(gap.gap_id)}
                      className="block w-full text-left text-xs px-2 py-1.5 rounded bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors"
                    >
                      <span className="font-medium">{gap.description}</span>
                      {gap.priority && (
                        <span
                          className={`ml-2 inline-block px-1 py-0.5 rounded text-[10px] font-bold ${
                            gap.priority === "high"
                              ? "bg-red-200 dark:bg-red-800 text-red-800 dark:text-red-200"
                              : gap.priority === "medium"
                                ? "bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200"
                                : "bg-blue-200 dark:bg-blue-800 text-blue-800 dark:text-blue-200"
                          }`}
                        >
                          {gap.priority}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

          {/* Recommended next actions */}
          {assessment.recommended_next_actions &&
            assessment.recommended_next_actions.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                  Recommended Actions
                </h4>
                <ul className="list-disc list-inside text-xs text-gray-700 dark:text-gray-300 space-y-0.5">
                  {assessment.recommended_next_actions.map((action, i) => (
                    <li key={i}>{action}</li>
                  ))}
                </ul>
              </div>
            )}
        </div>
      )}
    </div>
  );
}
