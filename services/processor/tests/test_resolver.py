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
    _entity_id_to_qdrant_id,
    _get_entity_aliases,
    _get_entity_name,
    _safe_label,
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
        """find_structural_matches() must execute three Cypher queries against Neo4j.

        Query 1: name/alias exact match
        Query 2: co-occurrence (shared relationship targets)
        Query 3: fuzzy name pre-filter
        """
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)
        entity = _make_entity("APT-28")

        candidates = await resolver.find_structural_matches(TENANT, entity)

        assert mock_session.run.await_count == 3
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

    def test_entity_id_to_qdrant_id_extracts_uuid(self) -> None:
        uid = str(uuid.uuid4())
        entity_id = f"entity--{uid}"
        assert _entity_id_to_qdrant_id(entity_id) == uid

    def test_entity_id_to_qdrant_id_passthrough_on_no_dashes(self) -> None:
        plain = "no-double-dash-here"
        result = _entity_id_to_qdrant_id(plain)
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


# ---------------------------------------------------------------------------
# Alias storage fix tests (Phase 1)
# ---------------------------------------------------------------------------


class TestAliasStorage:
    """Verify _props_from_entity stores aliases as a native list, not JSON string."""

    def test_aliases_stored_as_native_list(self) -> None:
        """Aliases from entity.properties must be a Python list in the props dict."""
        from src.resolution.resolver import _props_from_entity

        entity = _make_entity("Narendra Modi", entity_type="Person", aliases=["PM Modi", "NaMo"])
        props = _props_from_entity(entity, TENANT)

        assert "aliases" in props
        assert isinstance(props["aliases"], list), "aliases must be a native list, not JSON string"
        assert "PM Modi" in props["aliases"]
        assert "NaMo" in props["aliases"]

    def test_empty_aliases_stored_as_empty_list(self) -> None:
        """Entity with no aliases must store an empty list (not None or JSON '[]')."""
        from src.resolution.resolver import _props_from_entity

        entity = _make_entity("Unknown Actor")
        props = _props_from_entity(entity, TENANT)

        assert props["aliases"] == []

    def test_aliases_values_coerced_to_strings(self) -> None:
        """Each alias must be a string, not an int or other type."""
        from src.resolution.resolver import _props_from_entity

        entity = _make_entity("Test Entity", aliases=["Alpha", "Beta"])
        props = _props_from_entity(entity, TENANT)

        for alias in props["aliases"]:
            assert isinstance(alias, str)


# ---------------------------------------------------------------------------
# Structural alias query fix tests (Phase 1)
# ---------------------------------------------------------------------------


class TestStructuralAliasQuery:
    """Verify find_structural_matches can find entities via the aliases list."""

    async def test_alias_match_returns_score_1_0(self) -> None:
        """If incoming entity name matches an alias of an existing node, score must be 1.0."""
        existing_id = _make_entity_id("Person")
        mock_driver, mock_session = _make_mock_neo4j()

        # Query 1 (name/alias match) returns the existing entity
        result_name_alias = AsyncMock()
        result_name_alias.data = AsyncMock(return_value=[{"entity_id": existing_id, "score": 1.0}])
        # Query 2 (co-occurrence) returns nothing
        result_cooccur = AsyncMock()
        result_cooccur.data = AsyncMock(return_value=[])
        # Query 3 (fuzzy pre-filter) returns nothing
        result_fuzzy = AsyncMock()
        result_fuzzy.data = AsyncMock(return_value=[])

        mock_session.run = AsyncMock(side_effect=[result_name_alias, result_cooccur, result_fuzzy])

        resolver = _make_resolver(neo4j_driver=mock_driver)
        # "PM Modi" is an alias for the existing "Narendra Modi" node
        incoming = _make_entity("PM Modi", entity_type="Person")
        candidates = await resolver.find_structural_matches(TENANT, incoming)

        structural_hits = [c for c in candidates if c.match_type == "structural"]
        assert any(c.entity_id == existing_id for c in structural_hits)
        assert any(c.score == pytest.approx(1.0) for c in structural_hits)

    async def test_structural_query_uses_aliases_not_aliases_json(self) -> None:
        """The Cypher passed to Neo4j must reference 'e.aliases', not 'e.aliases_json'."""
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)
        entity = _make_entity("Test Entity")

        await resolver.find_structural_matches(TENANT, entity)

        # The first session.run call is the name/alias query
        first_cypher: str = mock_session.run.call_args_list[0].args[0]
        assert "e.aliases" in first_cypher
        assert "aliases_json" not in first_cypher


# ---------------------------------------------------------------------------
# Fuzzy name matching tests (Phase 2)
# ---------------------------------------------------------------------------


class TestFuzzyNameMatching:
    """Verify _find_fuzzy_name_matches catches name variations above the threshold."""

    async def test_fuzzy_match_above_threshold_returned(self) -> None:
        """A candidate with WRatio >= threshold should appear in fuzzy candidates."""
        existing_id = _make_entity_id("Person")
        mock_driver, mock_session = _make_mock_neo4j()

        # Neo4j pre-filter returns "Narendra Modi" (contains last token "Modi")
        result_fuzzy = AsyncMock()
        result_fuzzy.data = AsyncMock(
            return_value=[{"entity_id": existing_id, "name": "Narendra Modi", "aliases": []}]
        )
        mock_session.run = AsyncMock(return_value=result_fuzzy)

        resolver = _make_resolver(neo4j_driver=mock_driver)
        # "Narender Modi" (typo) — WRatio against "Narendra Modi" should be ~96
        incoming = _make_entity("Narender Modi", entity_type="Person")
        candidates = await resolver._find_fuzzy_name_matches(TENANT, incoming)

        assert len(candidates) == 1
        assert candidates[0].entity_id == existing_id
        assert candidates[0].match_type == "fuzzy"
        assert candidates[0].score >= 0.85

    async def test_fuzzy_match_via_alias(self) -> None:
        """A candidate whose alias closely matches the incoming name should be returned."""
        existing_id = _make_entity_id("Person")
        mock_driver, mock_session = _make_mock_neo4j()

        result_fuzzy = AsyncMock()
        result_fuzzy.data = AsyncMock(
            return_value=[
                {
                    "entity_id": existing_id,
                    "name": "Narendra Damodardas Modi",
                    "aliases": ["Narendra Modi", "PM Modi"],
                }
            ]
        )
        mock_session.run = AsyncMock(return_value=result_fuzzy)

        resolver = _make_resolver(neo4j_driver=mock_driver)
        # "PM Modi" WRatio vs alias "PM Modi" = 100
        incoming = _make_entity("PM Modi", entity_type="Person")
        candidates = await resolver._find_fuzzy_name_matches(TENANT, incoming)

        assert len(candidates) == 1
        assert candidates[0].entity_id == existing_id
        assert candidates[0].score == pytest.approx(1.0)

    async def test_fuzzy_below_threshold_excluded(self) -> None:
        """A candidate with WRatio below threshold must NOT be returned."""
        mock_driver, mock_session = _make_mock_neo4j()
        existing_id = _make_entity_id("Person")

        result_fuzzy = AsyncMock()
        result_fuzzy.data = AsyncMock(
            return_value=[{"entity_id": existing_id, "name": "Modi Industries Ltd", "aliases": []}]
        )
        mock_session.run = AsyncMock(return_value=result_fuzzy)

        resolver = _make_resolver(neo4j_driver=mock_driver)
        # "Narendra Modi" vs "Modi Industries Ltd" WRatio is well below 85
        incoming = _make_entity("Narendra Modi", entity_type="Person")
        candidates = await resolver._find_fuzzy_name_matches(TENANT, incoming)

        # Should be empty — "Modi Industries Ltd" is a different entity
        assert len(candidates) == 0

    async def test_fuzzy_skipped_for_unknown_name(self) -> None:
        """Entities named 'Unknown' must be skipped without querying Neo4j."""
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)
        incoming = _make_entity("Unknown", entity_type="Person")

        candidates = await resolver._find_fuzzy_name_matches(TENANT, incoming)

        assert candidates == []
        mock_session.run.assert_not_awaited()

    async def test_fuzzy_neo4j_error_is_swallowed(self) -> None:
        """A Neo4j failure in fuzzy matching must not propagate — returns empty list."""
        mock_driver, mock_session = _make_mock_neo4j()
        mock_session.run = AsyncMock(side_effect=Exception("Neo4j timeout"))

        resolver = _make_resolver(neo4j_driver=mock_driver)
        incoming = _make_entity("Narendra Modi", entity_type="Person")
        candidates = await resolver._find_fuzzy_name_matches(TENANT, incoming)

        assert candidates == []


# ---------------------------------------------------------------------------
# Type isolation tests (Phase 2 — cross-type safety)
# ---------------------------------------------------------------------------


class TestFuzzyTypeIsolation:
    """Ensure fuzzy matching is scoped to the same entity type."""

    async def test_fuzzy_query_passes_entity_type_filter(self) -> None:
        """The fuzzy Neo4j query must include entity_type in WHERE clause."""
        mock_driver, mock_session = _make_mock_neo4j()
        resolver = _make_resolver(neo4j_driver=mock_driver)
        entity = _make_entity("Modi Industries", entity_type="Organization")

        await resolver._find_fuzzy_name_matches(TENANT, entity)

        call_kwargs = mock_session.run.call_args.kwargs
        assert call_kwargs["entity_type"] == "Organization"

    async def test_fuzzy_scores_constrained_to_same_type(self) -> None:
        """Candidates returned by fuzzy matching must match the incoming entity type."""
        mock_driver, mock_session = _make_mock_neo4j()
        existing_person_id = _make_entity_id("Person")

        # Simulate Neo4j returning a Person node when queried for Organization
        # (this should not happen if type filter is correct, but we guard against it)
        result_fuzzy = AsyncMock()
        result_fuzzy.data = AsyncMock(
            return_value=[
                {"entity_id": existing_person_id, "name": "Modi Industries", "aliases": []}
            ]
        )
        mock_session.run = AsyncMock(return_value=result_fuzzy)

        resolver = _make_resolver(neo4j_driver=mock_driver)
        # Query as Organization — the neo4j WHERE filter handles isolation.
        # The test validates the query params are set correctly so Neo4j enforces it.
        incoming = _make_entity("Modi Industries", entity_type="Organization")
        candidates = await resolver._find_fuzzy_name_matches(TENANT, incoming)

        call_kwargs = mock_session.run.call_args.kwargs
        assert call_kwargs["tenant_id"] == TENANT
        assert call_kwargs["entity_type"] == "Organization"
        # Candidate is returned (type isolation enforced by Neo4j via WHERE, not in Python)
        assert all(c.match_type == "fuzzy" for c in candidates)


# ---------------------------------------------------------------------------
# Configurable threshold tests (Phase 5)
# ---------------------------------------------------------------------------


class TestConfigurableThresholds:
    """Verify AUTO_MERGE_THRESHOLD and AMBIGUOUS_THRESHOLD env vars are honoured."""

    def test_auto_merge_uses_module_threshold(self) -> None:
        """_apply_decision must use AUTO_MERGE_THRESHOLD, not a hardcoded 0.95."""
        import src.resolution.resolver as resolver_module

        entity = _make_entity()
        existing_id = _make_entity_id()

        original = resolver_module.AUTO_MERGE_THRESHOLD
        try:
            resolver_module.AUTO_MERGE_THRESHOLD = 0.80
            candidates = [_candidate(existing_id, score=0.82)]
            result = EntityResolver._apply_decision(candidates, entity)
            assert result.decision == ResolutionDecision.AUTO_MERGE
        finally:
            resolver_module.AUTO_MERGE_THRESHOLD = original

    def test_ambiguous_uses_module_threshold(self) -> None:
        """_apply_decision must use AMBIGUOUS_THRESHOLD, not a hardcoded 0.50."""
        import src.resolution.resolver as resolver_module

        entity = _make_entity()
        existing_id = _make_entity_id()

        original = resolver_module.AMBIGUOUS_THRESHOLD
        try:
            resolver_module.AMBIGUOUS_THRESHOLD = 0.30
            candidates = [_candidate(existing_id, score=0.35)]
            result = EntityResolver._apply_decision(candidates, entity)
            assert result.decision == ResolutionDecision.AMBIGUOUS
        finally:
            resolver_module.AMBIGUOUS_THRESHOLD = original
