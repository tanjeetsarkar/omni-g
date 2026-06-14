"""Enrichment publisher — fires entity-targeted enrichment requests to the Aggregator.

When the Processor discovers a new entity from raw feed content, or when a
user explicitly requests enrichment via the Delivery API, this module sends a
structured POST /enrich call to the Aggregator.  The Aggregator fans the
request out to configured MCP plugins, publishes the resulting raw events to
Kafka, and they re-enter the same processing pipeline — grounding validation
and all.

Key design principles:
- The Aggregator is the ONLY source of raw data.  This module never bypasses
  the Aggregator to write directly to Neo4j or Qdrant.
- Calls are fire-and-forget (HTTP 202 accepted).  The Processor does not block
  waiting for enrichment results.
- Rate limiting: at most ``ENRICHMENT_MAX_PER_ENTITY_PER_DAY`` requests per
  entity per tenant per day, enforced via an in-memory sliding window.  A
  Redis-backed version can replace this in Phase 5.
- Enrichment is NOT automatically triggered by the resolver.  The Delivery UI
  exposes a manual "Enrich" action per entity node; second-hop and deeper
  expansions require explicit user approval to prevent runaway recursion.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Maximum enrichment requests per entity (name+type+tenant key) per day.
ENRICHMENT_MAX_PER_ENTITY_PER_DAY: int = 5
_DAY_SECONDS: int = 86_400


class EnrichmentPublisher:
    """Sends enrichment requests to the Aggregator's POST /enrich endpoint.

    Instantiate once and reuse.  Thread-safe for asyncio (single event loop).

    Parameters
    ----------
    aggregator_url:
        Base URL of the Aggregator service (e.g. ``http://aggregator:8000``).
    http_timeout:
        Seconds to wait for the Aggregator to acknowledge the request.
    """

    def __init__(
        self,
        aggregator_url: str,
        http_timeout: float = 5.0,
    ) -> None:
        self._url = aggregator_url.rstrip("/") + "/enrich"
        self._timeout = http_timeout
        # In-memory rate limiter: {rate_key: [timestamp, ...]}
        self._request_log: dict[str, list[float]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def request_enrichment(
        self,
        entity_name: str,
        entity_type: str,
        tenant_id: str,
        description: str | None = None,
        plugins: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Request enrichment for a specific entity.

        Returns the Aggregator response dict on success, or ``None`` on failure
        or when rate-limited.

        Parameters
        ----------
        entity_name:
            The canonical name of the entity to enrich (e.g. ``"SpaceX"``).
        entity_type:
            The entity type label (e.g. ``"Organization"``).
        tenant_id:
            Tenant scope for the enrichment request.
        description:
            Optional short description to help plugins narrow the query.
        plugins:
            Optional list of plugin names to query.  ``None`` means all.
        """
        if not self._check_rate_limit(entity_name, entity_type, tenant_id):
            logger.info(
                "enrichment_rate_limited",
                extra={
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "tenant_id": tenant_id,
                },
            )
            return None

        payload: dict[str, Any] = {
            "entity": {
                "name": entity_name,
                "type": entity_type,
                **({"description": description} if description else {}),
            },
            "tenant_id": tenant_id,
            "plugins": plugins or [],
            "max_results": 50,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload)
                resp.raise_for_status()
                result: dict[str, Any] = resp.json()
                logger.info(
                    "enrichment_request_queued",
                    extra={
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                        "tenant_id": tenant_id,
                        "enrichment_id": result.get("enrichment_id"),
                        "events_queued": result.get("events_queued", 0),
                    },
                )
                self._record_request(entity_name, entity_type, tenant_id)
                return result
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "enrichment_request_http_error",
                extra={
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "tenant_id": tenant_id,
                    "status_code": exc.response.status_code,
                    "error": str(exc),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "enrichment_request_failed",
                extra={
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "tenant_id": tenant_id,
                    "error": str(exc),
                },
            )
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rate_key(self, entity_name: str, entity_type: str, tenant_id: str) -> str:
        return f"{tenant_id}::{entity_type}::{entity_name.lower()}"

    def _check_rate_limit(self, entity_name: str, entity_type: str, tenant_id: str) -> bool:
        """Return True if a new request is allowed under the daily cap."""
        key = self._rate_key(entity_name, entity_type, tenant_id)
        now = time.monotonic()
        cutoff = now - _DAY_SECONDS
        # Prune old entries
        self._request_log[key] = [t for t in self._request_log[key] if t >= cutoff]
        return len(self._request_log[key]) < ENRICHMENT_MAX_PER_ENTITY_PER_DAY

    def _record_request(self, entity_name: str, entity_type: str, tenant_id: str) -> None:
        key = self._rate_key(entity_name, entity_type, tenant_id)
        self._request_log[key].append(time.monotonic())
