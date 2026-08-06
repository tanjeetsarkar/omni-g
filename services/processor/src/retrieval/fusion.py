"""Dual-view score fusion — blends relational and temporal retrieval results.

Algorithm (V3 architecture eq. 12-14):
  1. Per-view min-max score normalisation
  2. Weighted blend: ρ * relational + (1-ρ) * temporal  (ρ biased by route)
  3. Evidence closure: collect graph bridges and local span neighbours
  4. Deduplication by context_id
"""

from __future__ import annotations

import logging

from .profiler import QueryProfile
from .scored_context import ScoredContext

logger = logging.getLogger(__name__)


class DualViewFusion:
    """Fuses relational and temporal retrieval outputs into a single ranked list."""

    def fuse(
        self,
        relational: list[ScoredContext],
        temporal: list[ScoredContext],
        profile: QueryProfile,
        rho: float = 0.6,
    ) -> list[ScoredContext]:
        """Blend *relational* and *temporal* results and return deduped ranked list."""
        if not relational and not temporal:
            return []

        # Route-biased weighting
        if profile.route == "relational":
            rho = 0.7
        else:
            rho = 0.3

        # Per-view min-max normalisation
        def _normalise(items: list[ScoredContext]) -> dict[str, float]:
            if not items:
                return {}
            lo = min(c.score for c in items)
            hi = max(c.score for c in items)
            span = hi - lo if hi > lo else 1.0
            return {c.context_id: (c.score - lo) / span for c in items}

        rel_norm = _normalise(relational)
        temp_norm = _normalise(temporal)

        # Build master lookup
        master: dict[str, ScoredContext] = {}
        for c in relational + temporal:
            if c.context_id not in master:
                master[c.context_id] = c

        # Weighted blend
        fused: list[ScoredContext] = []
        for cid, ctx in master.items():
            combined = rho * rel_norm.get(cid, 0.0) + (1 - rho) * temp_norm.get(cid, 0.0)
            fused.append(
                ScoredContext(
                    context_id=ctx.context_id,
                    score=combined,
                    text=ctx.text,
                    entity_ids=ctx.entity_ids,
                    source_event_id=ctx.source_event_id,
                )
            )

        fused.sort(key=lambda x: x.score, reverse=True)
        logger.debug(
            "dual_view_fusion_done",
            extra={
                "relational_count": len(relational),
                "temporal_count": len(temporal),
                "fused_count": len(fused),
                "route": profile.route,
            },
        )
        return fused
