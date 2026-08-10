"""Shared temporal hash utilities for ContextUnit hierarchy bucketing.

Extracted from ``pipeline.py`` so that both the ingestion pipeline and the
temporal retrieval layer use the *same* deterministic hash strategy for
session / episode / window IDs.  This closes the drift where
``retrieval/temporal.py`` re-implemented the episode hash with a hard-coded
``"unknown"`` domain, producing lookups that never matched ingested records.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import urlparse


def _h(key: str) -> str:
    """Return the first 12 hex chars of the SHA-256 digest of *key*."""
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def assign_temporal_ids(
    tenant_id: str,
    source: str | None,
    now: datetime,
    event_id: str,
) -> tuple[str, str, str, str]:
    """Deterministic bucket IDs derived from ingest metadata, no external state needed.

    Returns ``(session_id, episode_id, window_id, turn_id)``.

    - **session_id** — one per tenant per calendar day.
    - **episode_id** — one per tenant per source-domain per hour.
    - **window_id** — one per tenant per 15-minute window.
    - **turn_id** — the raw event ID (identity).
    """
    ts = int(now.timestamp())
    domain = urlparse(source or "").netloc or "unknown"
    session_id = _h(f"{tenant_id}:{now.date().isoformat()}")
    episode_id = _h(f"{tenant_id}:{domain}:{ts // 3600}")
    window_id = _h(f"{tenant_id}:{ts // 900}")
    return session_id, episode_id, window_id, event_id


def episode_id_for_cue(tenant_id: str, domain: str, ts: int) -> str:
    """Return the episode hash for a *domain* at a given Unix timestamp.

    Used by the temporal retriever to map a parsed temporal cue to the same
    episode bucket that ingestion would have produced for that hour.
    """
    return _h(f"{tenant_id}:{domain}:{ts // 3600}")
