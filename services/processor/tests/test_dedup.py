from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.dedup.deduplicator import ContentDeduplicator, _hash_event

# ===========================================================================
# Test group 1: check_and_set — core deduplication behaviour
# ===========================================================================


class TestCheckAndSet:
    """Core check-and-set deduplication logic."""

    async def test_new_event_returns_not_duplicate(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """First time an event is seen it must NOT be flagged as a duplicate."""
        event: dict[str, Any] = {"content": "unique event A", "source": "twitter"}
        result = await fake_deduplicator.check_and_set("tenant1", event)
        assert result.is_duplicate is False

    async def test_duplicate_event_returns_is_duplicate(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """Submitting the identical event a second time must return is_duplicate=True."""
        event: dict[str, Any] = {"content": "repeated event", "source": "feed"}
        first = await fake_deduplicator.check_and_set("tenant1", event)
        second = await fake_deduplicator.check_and_set("tenant1", event)
        assert first.is_duplicate is False
        assert second.is_duplicate is True

    async def test_different_events_not_deduplicated(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """Two events with different payloads must produce different hashes and both pass."""
        event_a: dict[str, Any] = {"content": "event alpha", "source": "twitter"}
        event_b: dict[str, Any] = {"content": "event beta", "source": "twitter"}
        result_a = await fake_deduplicator.check_and_set("tenant1", event_a)
        result_b = await fake_deduplicator.check_and_set("tenant1", event_b)
        assert result_a.is_duplicate is False
        assert result_b.is_duplicate is False
        assert result_a.content_hash != result_b.content_hash

    async def test_sliding_window_ttl_refreshes(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """Seeing a duplicate must reset (extend) the TTL of the dedup key."""
        event: dict[str, Any] = {"content": "ttl test event", "source": "rss"}
        await fake_deduplicator.check_and_set("tenant1", event)

        content_hash = _hash_event(event)
        key = f"dedup:tenant1:{content_hash}"

        # Artificially reduce the TTL so we can detect a refresh
        assert fake_deduplicator._client is not None
        await fake_deduplicator._client.expire(key, 5)
        ttl_before = await fake_deduplicator._client.ttl(key)
        assert ttl_before <= 5

        # Seeing the same event again should trigger EXPIRE → full TTL
        dup_result = await fake_deduplicator.check_and_set("tenant1", event)
        assert dup_result.is_duplicate is True
        ttl_after = await fake_deduplicator._client.ttl(key)
        assert ttl_after > 5

    async def test_tenant_isolation(self, fake_deduplicator: ContentDeduplicator) -> None:
        """The same payload submitted under different tenant IDs must NOT deduplicate."""
        event: dict[str, Any] = {"content": "shared content", "source": "twitter"}
        result_t1 = await fake_deduplicator.check_and_set("tenant_alpha", event)
        result_t2 = await fake_deduplicator.check_and_set("tenant_beta", event)
        assert result_t1.is_duplicate is False
        assert result_t2.is_duplicate is False

    async def test_redis_unavailable_fails_open(self) -> None:
        """When the Redis client is not initialised the call must fail-open."""
        dedup = ContentDeduplicator(ttl_seconds=60)
        # Intentionally skip connect() so _client remains None
        result = await dedup.check_and_set("tenant1", {"content": "any event"})
        assert result.is_duplicate is False

    async def test_event_id_extracted_from_payload(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """When the event dict has an event_id field it must be propagated in DedupResult."""
        event: dict[str, Any] = {"event_id": "evt-42", "content": "intel report", "source": "rss"}
        result = await fake_deduplicator.check_and_set("tenant1", event)
        assert result.event_id == "evt-42"

    async def test_event_without_event_id_has_none(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """Events that lack an event_id field must return event_id=None."""
        event: dict[str, Any] = {"content": "no id here"}
        result = await fake_deduplicator.check_and_set("tenant1", event)
        assert result.event_id is None


# ===========================================================================
# Test group 2: hashing determinism
# ===========================================================================


class TestHashing:
    """SHA-256 hashing determinism and canonical form."""

    def test_hash_is_deterministic(self) -> None:
        """Hashing the same event twice must produce the same digest."""
        event: dict[str, Any] = {"b": 2, "a": 1, "c": 3}
        assert _hash_event(event) == _hash_event(event)

    def test_content_hash_uses_sorted_keys(self) -> None:
        """The hash must be computed on sorted-key JSON regardless of insertion order."""
        unordered: dict[str, Any] = {"b": 2, "a": 1}
        ordered: dict[str, Any] = {"a": 1, "b": 2}

        # Expected digest: sha256 of '{"a": 1, "b": 2}' (sort_keys=True)
        expected = hashlib.sha256(
            json.dumps({"a": 1, "b": 2}, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()

        assert _hash_event(unordered) == expected
        assert _hash_event(unordered) == _hash_event(ordered)


# ===========================================================================
# Test group 3: RediSearch find_similar
# ===========================================================================


class TestFindSimilar:
    """Botnet-dedup clustering via RediSearch FT.SEARCH."""

    async def test_find_similar_returns_matching_keys(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """find_similar must return key IDs reported by FT.SEARCH."""
        fake_deduplicator._has_redisearch = True

        mock_doc = MagicMock()
        mock_doc.id = "dedup:tenant1:abc123"
        mock_result = MagicMock()
        mock_result.docs = [mock_doc]

        mock_ft_cmd = MagicMock()
        mock_ft_cmd.search = AsyncMock(return_value=mock_result)

        assert fake_deduplicator._client is not None
        with patch.object(fake_deduplicator._client, "ft", return_value=mock_ft_cmd):
            keys = await fake_deduplicator.find_similar("tenant1", "twitter")

        assert keys == ["dedup:tenant1:abc123"]

    async def test_find_similar_without_redisearch_returns_empty(
        self, fake_deduplicator: ContentDeduplicator
    ) -> None:
        """find_similar must return [] when RediSearch is not available."""
        # _has_redisearch is False by default in the fixture
        keys = await fake_deduplicator.find_similar("tenant1", "twitter")
        assert keys == []
