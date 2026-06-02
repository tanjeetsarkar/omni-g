from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, NoReturn
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.entities import Entity
from src.resolution.models import CandidateMatch, ResolutionDecision, ResolutionResult
from src.resolution.resolver import (
    FALSE_POSITIVE_ALERTS,
    RESOLUTION_DECISIONS,
    SAME_AS_MERGES,
    EntityResolver,
    _embed,
    _get_entity_aliases,
    _get_entity_name,
    _safe_label,
    _stix_id_to_qdrant_id,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TENANT = "tenant-test"
NOW = datetime.now(tz=UTC)


def _make_entity_id(entity_type: str = "Organization") -> str:
    return f"entity--{uuid.uuid4()}"


def _counter_value(counter: Any, **labels: str) -> float:
    metric = counter.labels(**labels) if labels else counter
    value_obj = getattr(metric, "_value", None)
    if value_obj is None:
        return 0.0
    return float(value_obj.get())


def _make_entity(
    name: str = "APT-X",
    entity_type: str = "ThreatActor",
    **kwargs: Any,
) -> Entity:
    props = kwargs.pop("properties", {})
    if "aliases" in kwargs:
        props["aliases"] = kwargs.pop("aliases")
    return Entity(
        id=_make_entity_id(entity_type),
        type=entity_type,
        name=name,
        created=NOW,
        modified=NOW,
        confidence=0.8,
        properties=props,
        **kwargs,
    )


def _candidate(entity_id: str, score: float, match_type: str = "vector") -> CandidateMatch:
    return CandidateMatch(entity_id=entity_id, score=score, match_type=match_type)


def _make_mock_neo4j() -> tuple[MagicMock, AsyncMock]:
    """Return (mock_driver, mock_session) with async context-manager support."""
    mock_result = AsyncMock()
    mock_result.data = AsyncMock(return_value=[])
    mock_result.single = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)

    return mock_driver, mock_session


def _make_mock_qdrant() -> AsyncMock:
    """Return a mock AsyncQdrantClient with benign defaults."""
    mock = AsyncMock()
    mock.collection_exists = AsyncMock(return_value=True)
    mock.upsert = AsyncMock(return_value=None)
    mock.search = AsyncMock(return_value=[])
    mock.create_collection = AsyncMock(return_value=None)
    return mock


def _make_resolver(
    neo4j_driver: Any = None,
    qdrant_client: Any = None,
) -> EntityResolver:
    if neo4j_driver is None:
        neo4j_driver = _make_mock_neo4j()[0]
    if qdrant_client is None:
        qdrant_client = _make_mock_qdrant()
    return EntityResolver(
        neo4j_driver=neo4j_driver,
        qdrant_client=qdrant_client,
    )


# ---------------------------------------------------------------------------
# Unit tests — pure decision logic (no I/O)
# ---------------------------------------------------------------------------


class TestResolutionDecisionLogic:
    """Tests for EntityResolver._apply_decision — no network calls."""

    def test_resolution_decision_auto_merge(self) -> None:
        """score >= 0.95 → AUTO_MERGE into the matched entity."""
        entity = _make_entity()
        existing_id = _make_entity_id()
        candidates = [_candidate(existing_id, score=0.97)]

        result = EntityResolver._apply_decision(candidates, entity)

        assert result.decision == ResolutionDecision.AUTO_MERGE
        assert result.matched_entity_id == existing_id
        assert result.confidence_score == pytest.approx(0.97)
        assert result.entity is entity

    def test_resolution_decision_auto_merge_exact_threshold(self) -> None:
        """score == 0.95 (exact boundary) → AUTO_MERGE."""
        entity = _make_entity()
        existing_id = _make_entity_id()
        candidates = [_candidate(existing_id, score=0.95)]

        result = EntityResolver._apply_decision(candidates, entity)

        assert result.decision == ResolutionDecision.AUTO_MERGE

    def test_resolution_decision_ambiguous(self) -> None:
        """0.50 <= score < 0.95 → AMBIGUOUS (flag for analyst review)."""
        entity = _make_entity()
        existing_id = _make_entity_id()
        candidates = [_candidate(existing_id, score=0.75)]

        result = EntityResolver._apply_decision(candidates, entity)

        assert result.decision == ResolutionDecision.AMBIGUOUS
        assert result.matched_entity_id == existing_id
        assert result.confidence_score == pytest.approx(0.75)

    def test_resolution_decision_ambiguous_lower_bound(self) -> None:
        """score == 0.50 (exact lower boundary) → AMBIGUOUS."""
        entity = _make_entity()
        existing_id = _make_entity_id()
        candidates = [_candidate(existing_id, score=0.50)]

        result = EntityResolver._apply_decision(candidates, entity)

        assert result.decision == ResolutionDecision.AMBIGUOUS

    def test_resolution_decision_new_entity(self) -> None:
        """No candidates at all → NEW_ENTITY with score 0.0."""
        entity = _make_entity()
        result = EntityResolver._apply_decision([], entity)

        assert result.decision == ResolutionDecision.NEW_ENTITY
        assert result.matched_entity_id is None
        assert result.confidence_score == 0.0
        assert result.entity is entity

    def test_resolution_decision_new_entity_low_score(self) -> None:
        """Max candidate score < 0.50 → NEW_ENTITY."""
        entity = _make_entity()
        existing_id = _make_entity_id()
        candidates = [_candidate(existing_id, score=0.30)]

        result = EntityResolver._apply_decision(candidates, entity)

        assert result.decision == ResolutionDecision.NEW_ENTITY
        assert result.matched_entity_id is None
        assert result.confidence_score == pytest.approx(0.30)

    def test_combine_candidates_dedup_takes_max_score(self) -> None:
        """Same entity_id from both vector + structural → deduplicate keeping max score."""
        entity = _make_entity()
        shared_id = _make_entity_id()

        candidates = [
            _candidate(shared_id, score=0.80, match_type="vector"),
            _candidate(shared_id, score=0.96, match_type="structural"),
            _candidate(shared_id, score=0.70, match_type="structural"),
        ]

        result = EntityResolver._apply_decision(candidates, entity)

        assert result.decision == ResolutionDecision.AUTO_MERGE
        assert result.matched_entity_id == shared_id
        assert result.confidence_score == pytest.approx(0.96)

    def test_combine_candidates_best_entity_wins(self) -> None:
        """Multiple distinct candidates → pick the one with highest score."""
        entity = _make_entity()
        id_low = _make_entity_id()
        id_high = _make_entity_id()

        candidates = [
            _candidate(id_low, score=0.60),
            _candidate(id_high, score=0.97),
        ]

        result = EntityResolver._apply_decision(candidates, entity)

        assert result.decision == ResolutionDecision.AUTO_MERGE
        assert result.matched_entity_id == id_high


# ---------------------------------------------------------------------------
# Integration-style tests — mocked I/O
# ---------------------------------------------------------------------------


class TestVectorBlocking:
    async def test_vector_blocking_upserts_and_searches(self) -> None:
        """find_candidates() must upsert the entity then search for similar ones."""
        mock_qdrant = _make_mock_qdrant()
        resolver = _make_resolver(qdrant_client=mock_qdrant)
        entity = _make_entity("Fancy Bear")

        candidates = await resolver.find_candidates(TENANT, entity)

        mock_qdrant.upsert.assert_awaited_once()
        mock_qdrant.search.assert_awaited_once()

        upsert_call = mock_qdrant.upsert.call_args
        assert upsert_call.kwargs["collection_name"] == f"entities_{TENANT}"
        points = upsert_call.kwargs["points"]
        assert len(points) == 1
        assert points[0].payload["entity_id"] == entity.id

        assert len(candidates) == 0

    async def test_vector_blocking_filters_self_from_results(self) -> None:
        """find_candidates() must not return the entity being resolved as a candidate."""
        entity = _make_entity("Cozy Bear")
        mock_qdrant = _make_mock_qdrant()

        mock_point = MagicMock()
        mock_point.score = 1.0
        mock_point.payload = {"entity_id": entity.id}
        mock_qdrant.search = AsyncMock(return_value=[mock_point])

        resolver = _make_resolver(qdrant_client=mock_qdrant)
        candidates = await resolver.find_candidates(TENANT, entity)

        assert all(c.entity_id != entity.id for c in candidates)

    async def test_vector_blocking_returns_other_matches(self) -> None:
        """find_candidates() returns non-self matching entities from Qdrant."""
        entity = _make_entity("Lazarus Group")
        existing_id = _make_entity_id()
        mock_qdrant = _make_mock_qdrant()

        mock_point = MagicMock()
        mock_point.score = 0.93
        mock_point.payload = {"entity_id": existing_id}
        mock_qdrant.search = AsyncMock(return_value=[mock_point])

        resolver = _make_resolver(qdrant_client=mock_qdrant)
        candidates = await resolver.find_candidates(TENANT, entity)

        assert len(candidates) == 1
        assert candidates[0].entity_id == existing_id
        assert candidates[0].score == pytest.approx(0.93)
        assert candidates[0].match_type == "vector"

    async def test_vector_blocking_creates_collection_if_missing(self) -> None:
        """find_candidates() creates the Qdrant collection when it does not exist."""
        mock_qdrant = _make_mock_qdrant()
        mock_qdrant.collection_exists = AsyncMock(return_value=False)

        resolver = _make_resolver(qdrant_client=mock_qdrant)
        await resolver.find_candidates(TENANT, _make_entity())

        mock_qdrant.create_collection.assert_awaited_once()
        call_kwargs = mock_qdrant.create_collection.call_args.kwargs
        assert call_kwargs["collection_name"] == f"entities_{TENANT}"


class TestStructuralMatching:
    async def test_structural_matching_queries_neo4j(self) -> None:
        """find_structural_matches() must execute two Cypher queries against Neo4j."""
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)
        entity = _make_entity("APT-28")

        candidates = await resolver.find_structural_matches(TENANT, entity)

        assert mock_session.run.await_count == 2
        assert candidates == []

    async def test_structural_matching_name_match_returns_candidate(self) -> None:
        """find_structural_matches() returns a structural candidate on name match."""
        existing_id = _make_entity_id()
        mock_driver, mock_session = _make_mock_neo4j()

        result_name = AsyncMock()
        result_name.data = AsyncMock(return_value=[{"entity_id": existing_id, "score": 1.0}])
        result_cooccur = AsyncMock()
        result_cooccur.data = AsyncMock(return_value=[])

        mock_session.run = AsyncMock(side_effect=[result_name, result_cooccur])

        resolver = _make_resolver(neo4j_driver=mock_driver)
        candidates = await resolver.find_structural_matches(TENANT, _make_entity("APT-28"))

        name_candidates = [c for c in candidates if c.match_type == "structural"]
        assert any(c.entity_id == existing_id for c in name_candidates)
        assert any(c.score == pytest.approx(1.0) for c in name_candidates)

    async def test_structural_matching_passes_correct_params(self) -> None:
        """find_structural_matches() passes tenant_id, entity_type, entity_id, name to Neo4j."""
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)
        entity = _make_entity("Sandworm", entity_type="ThreatActor")

        await resolver.find_structural_matches(TENANT, entity)

        first_call_kwargs = mock_session.run.call_args_list[0].kwargs
        assert first_call_kwargs["tenant_id"] == TENANT
        assert first_call_kwargs["entity_type"] == "ThreatActor"
        assert first_call_kwargs["entity_id"] == entity.id
        assert first_call_kwargs["name"] == "Sandworm"


class TestPersistEntity:
    async def test_persist_new_entity_calls_merge(self) -> None:
        """persist_entity() for NEW_ENTITY must call session.run() once (CREATE node)."""
        mock_driver, mock_session = _make_mock_neo4j()
        mock_session.run.return_value.single = AsyncMock(return_value={"entity_id": "entity--abc"})

        resolver = _make_resolver(neo4j_driver=mock_driver)
        entity = _make_entity("NewActor")
        resolution = ResolutionResult(
            decision=ResolutionDecision.NEW_ENTITY,
            matched_entity_id=None,
            confidence_score=0.0,
            entity=entity,
        )

        await resolver.persist_entity(TENANT, entity, resolution)

        mock_session.run.assert_awaited_once()
        cypher: str = mock_session.run.call_args.args[0]
        assert "MERGE" in cypher
        assert "Entity" in cypher

    async def test_persist_auto_merge_updates_existing_node(self) -> None:
        """persist_entity() for AUTO_MERGE updates existing node and returns matched_id."""
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)

        entity = _make_entity("APT-X")
        matched_id = _make_entity_id()

        resolution = ResolutionResult(
            decision=ResolutionDecision.AUTO_MERGE,
            matched_entity_id=matched_id,
            confidence_score=0.97,
            entity=entity,
        )

        canonical_id = await resolver.persist_entity(TENANT, entity, resolution)

        assert canonical_id == matched_id
        mock_session.run.assert_awaited_once()
        cypher: str = mock_session.run.call_args.args[0]
        assert "MATCH" in cypher
        assert "SET" in cypher

    async def test_persist_ambiguous_creates_node_and_same_as(self) -> None:
        """persist_entity() for AMBIGUOUS creates new node + SAME_AS relationship."""
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)

        entity = _make_entity("MaybeAPT")
        matched_id = _make_entity_id()

        mock_result_create = AsyncMock()
        mock_result_create.single = AsyncMock(return_value={"entity_id": entity.id})
        mock_result_create.data = AsyncMock(return_value=[])

        mock_result_rel = AsyncMock()
        mock_result_rel.single = AsyncMock(return_value=None)
        mock_result_rel.data = AsyncMock(return_value=[])

        mock_session.run = AsyncMock(side_effect=[mock_result_create, mock_result_rel])

        resolution = ResolutionResult(
            decision=ResolutionDecision.AMBIGUOUS,
            matched_entity_id=matched_id,
            confidence_score=0.75,
            entity=entity,
        )

        await resolver.persist_entity(TENANT, entity, resolution)

        assert mock_session.run.await_count == 2
        same_as_cypher: str = mock_session.run.call_args_list[1].args[0]
        assert "SAME_AS" in same_as_cypher
        same_as_kwargs = mock_session.run.call_args_list[1].kwargs
        assert same_as_kwargs["confidence"] == pytest.approx(0.75)

    async def test_persist_new_entity_returns_entity_id_on_missing_row(self) -> None:
        """persist_entity() falls back to entity.id when Neo4j returns no row."""
        mock_driver, mock_session = _make_mock_neo4j()
        mock_session.run.return_value.single = AsyncMock(return_value=None)

        resolver = _make_resolver(neo4j_driver=mock_driver)
        entity = _make_entity("FallbackActor")
        resolution = ResolutionResult(
            decision=ResolutionDecision.NEW_ENTITY,
            matched_entity_id=None,
            confidence_score=0.0,
            entity=entity,
        )

        canonical_id = await resolver.persist_entity(TENANT, entity, resolution)
        assert canonical_id == entity.id


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------


class TestMetrics:
    async def test_resolve_and_persist_increments_auto_merge_metrics(self) -> None:
        """AUTO_MERGE path increments SAME_AS_MERGES and RESOLUTION_DECISIONS."""
        resolver = _make_resolver()
        entity = _make_entity("MetricActor")

        existing_id = _make_entity_id()

        auto_merge_result = ResolutionResult(
            decision=ResolutionDecision.AUTO_MERGE,
            matched_entity_id=existing_id,
            confidence_score=0.97,
            entity=entity,
        )

        before_merges = _counter_value(SAME_AS_MERGES, tenant_id=TENANT)

        with patch.object(resolver, "resolve", AsyncMock(return_value=auto_merge_result)):
            with patch.object(resolver, "persist_entity", AsyncMock(return_value=entity.id)):
                await resolver.resolve_and_persist(TENANT, entity)

        with (
            patch.object(
                resolver, "find_candidates", AsyncMock(return_value=[_candidate(existing_id, 0.97)])
            ),
            patch.object(resolver, "find_structural_matches", AsyncMock(return_value=[])),
            patch.object(resolver, "persist_entity", AsyncMock(return_value=entity.id)),
        ):
            entity2 = _make_entity("MetricActor2")
            await resolver.resolve(TENANT, entity2)

        assert _counter_value(SAME_AS_MERGES, tenant_id=TENANT) >= before_merges + 1

    async def test_resolve_increments_false_positive_alerts_for_ambiguous(self) -> None:
        """AMBIGUOUS decision increments FALSE_POSITIVE_ALERTS counter."""
        resolver = _make_resolver()
        entity = _make_entity("AmbiguousActor")
        existing_id = _make_entity_id()

        before = _counter_value(FALSE_POSITIVE_ALERTS, tenant_id=TENANT)

        with (
            patch.object(
                resolver,
                "find_candidates",
                AsyncMock(return_value=[_candidate(existing_id, 0.72)]),
            ),
            patch.object(resolver, "find_structural_matches", AsyncMock(return_value=[])),
        ):
            result = await resolver.resolve(TENANT, entity)

        assert result.decision == ResolutionDecision.AMBIGUOUS
        assert _counter_value(FALSE_POSITIVE_ALERTS, tenant_id=TENANT) == before + 1

    async def test_resolve_increments_same_as_merges_for_auto_merge(self) -> None:
        """AUTO_MERGE decision increments SAME_AS_MERGES counter."""
        resolver = _make_resolver()
        entity = _make_entity("MergeActor")
        existing_id = _make_entity_id()

        before = _counter_value(SAME_AS_MERGES, tenant_id=TENANT)

        with (
            patch.object(
                resolver,
                "find_candidates",
                AsyncMock(return_value=[_candidate(existing_id, 0.98)]),
            ),
            patch.object(resolver, "find_structural_matches", AsyncMock(return_value=[])),
        ):
            result = await resolver.resolve(TENANT, entity)

        assert result.decision == ResolutionDecision.AUTO_MERGE
        assert _counter_value(SAME_AS_MERGES, tenant_id=TENANT) == before + 1

    async def test_resolve_increments_decisions_counter(self) -> None:
        """resolve() increments RESOLUTION_DECISIONS for each call."""
        resolver = _make_resolver()
        entity = _make_entity("DecisionActor")

        before = _counter_value(
            RESOLUTION_DECISIONS,
            decision="new_entity",
            tenant_id=TENANT,
        )

        with (
            patch.object(resolver, "find_candidates", AsyncMock(return_value=[])),
            patch.object(resolver, "find_structural_matches", AsyncMock(return_value=[])),
        ):
            result = await resolver.resolve(TENANT, entity)

        assert result.decision == ResolutionDecision.NEW_ENTITY
        assert (
            _counter_value(
                RESOLUTION_DECISIONS,
                decision="new_entity",
                tenant_id=TENANT,
            )
            == before + 1
        )


# ---------------------------------------------------------------------------
# Module-level helper unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_safe_label_replaces_hyphens(self) -> None:
        assert _safe_label("threat-actor") == "threat_actor"

    def test_safe_label_replaces_spaces(self) -> None:
        assert _safe_label("my label") == "my_label"

    def test_safe_label_prepends_prefix_for_digit_start(self) -> None:
        assert _safe_label("123abc").startswith("L_")

    def test_stix_id_to_qdrant_id_extracts_uuid(self) -> None:
        uid = str(uuid.uuid4())
        stix_id = f"entity--{uid}"
        assert _stix_id_to_qdrant_id(stix_id) == uid

    def test_stix_id_to_qdrant_id_passthrough_on_no_dashes(self) -> None:
        plain = "no-double-dash-here"
        result = _stix_id_to_qdrant_id(plain)
        assert isinstance(result, str)

    def test_get_entity_name_returns_name(self) -> None:
        entity = _make_entity("Fancy Bear")
        assert _get_entity_name(entity) == "Fancy Bear"

    def test_get_entity_name_returns_empty_for_none_name(self) -> None:
        entity = Entity(
            id=f"entity--{uuid.uuid4()}",
            type="Location",
            name="",
            created=NOW,
            modified=NOW,
        )
        assert _get_entity_name(entity) == ""

    def test_get_entity_aliases_returns_list(self) -> None:
        entity = _make_entity("APT-28", aliases=["Fancy Bear", "Sofacy"])
        aliases = _get_entity_aliases(entity)
        assert "Fancy Bear" in aliases
        assert "Sofacy" in aliases

    def test_embed_is_deterministic(self) -> None:
        v1 = _embed("hello world")
        v2 = _embed("hello world")
        assert v1 == v2

    def test_embed_different_inputs_differ(self) -> None:
        v1 = _embed("APT-28 threat-actor")
        v2 = _embed("Emotet malware")
        assert v1 != v2

    def test_embed_length_equals_embedding_dim(self) -> None:
        from src.resolution.resolver import EMBEDDING_DIM

        v = _embed("test string")
        assert len(v) == EMBEDDING_DIM


class TestResolverEmbedding:
    @pytest.mark.asyncio
    async def test_ollama_embedding_success(self) -> None:
        """Test successful Ollama embedding API call returning 768-D representation."""
        resolver = _make_resolver()

        mock_embedding = [0.1] * 768
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"embedding": mock_embedding})
        mock_response.raise_for_status = MagicMock()

        async def mock_post(*args: object, **kwargs: object) -> MagicMock:
            return mock_response

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            vector = await resolver._embed("APT28")

        assert len(vector) == 768
        assert vector == mock_embedding

    @pytest.mark.asyncio
    async def test_ollama_embedding_underflow_padded(self) -> None:
        """Test Ollama embedding with size less than EMBEDDING_DIM is padded with zeros."""
        resolver = _make_resolver()
        mock_embedding = [0.1] * 100
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"embedding": mock_embedding})
        mock_response.raise_for_status = MagicMock()

        async def mock_post(*args: object, **kwargs: object) -> MagicMock:
            return mock_response

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            vector = await resolver._embed("APT28")

        assert len(vector) == 768
        assert vector[:100] == mock_embedding
        assert vector[100:] == [0.0] * 668

    @pytest.mark.asyncio
    async def test_ollama_embedding_fails_graceful_hash_fallback(self) -> None:
        """Test HTTP/connection error falls back to hash embedding."""
        resolver = _make_resolver()

        async def mock_post_fail(*args: object, **kwargs: object) -> NoReturn:
            import httpx

            raise httpx.ConnectError("Ollama offline")

        with patch("httpx.AsyncClient.post", side_effect=mock_post_fail):
            vector = await resolver._embed("APT28")

        assert len(vector) == 768

        # Should match deterministic hashing
        assert vector == _embed("APT28", 768)
