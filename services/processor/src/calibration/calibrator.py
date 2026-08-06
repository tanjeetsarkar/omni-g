"""Evidence calibrator — prunes and ranks retrieved context chains before
handing them to the reader LLM (Delivery synthesis).

Algorithm (V3 architecture eq. 15):
  1. Filter out empty or boundary-violating contexts
  2. Rank by relevance score (already done by fusion)
  3. Apply token-budget cutoff (l_max tokens ≈ l_max * 4 chars)
  4. Deduplicate overlapping text spans
"""

from __future__ import annotations

import logging

from ..retrieval.profiler import QueryProfile
from ..retrieval.scored_context import ScoredContext

logger = logging.getLogger(__name__)

# Conservative chars-per-token approximation
_CHARS_PER_TOKEN = 4


class EvidenceCalibrator:
    """Prunes a ranked list of ScoredContext objects to fit within *l_max* tokens."""

    def calibrate(
        self,
        candidates: list[ScoredContext],
        profile: QueryProfile,
        l_max: int = 4096,
    ) -> list[ScoredContext]:
        """Return a calibrated, deduplicated list of ScoredContext within budget.

        Steps:
        - Drop empty texts
        - Deduplicate near-identical spans (first 100 chars as fingerprint)
        - Cut off once the cumulative token estimate exceeds *l_max*
        """
        if not candidates:
            return []

        token_budget = l_max * _CHARS_PER_TOKEN

        valid = [c for c in candidates if c.text.strip()]

        # Deduplication by first-100-char fingerprint
        seen: set[str] = set()
        deduped: list[ScoredContext] = []
        for ctx in valid:
            fp = ctx.text[:100].strip().lower()
            if fp not in seen:
                seen.add(fp)
                deduped.append(ctx)

        # Token-budget cutoff
        result: list[ScoredContext] = []
        used = 0
        for ctx in deduped:
            if used + len(ctx.text) > token_budget:
                break
            result.append(ctx)
            used += len(ctx.text)

        logger.debug(
            "calibration_done",
            extra={
                "input_count": len(candidates),
                "output_count": len(result),
                "chars_used": used,
                "budget": token_budget,
            },
        )
        return result
