from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphrag.community import CommunityDetector, CommunityResult, _connected_components
from src.graphrag.indexer import GraphRAGIndexer, IndexingResult
from src.graphrag.summarizer import CommunitySummarizer, CommunitySummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)


def _make_community(cid: int = 0, n: int = 3, tenant_id: str = "t1") -> CommunityResult:
    return CommunityResult(
        community_id=cid,
        entity_ids=[f"threat-actor--00000000-0000-0000-0000-{i:012d}" for i in range(n)],
        tenant_id=tenant_id,
        algorithm="leiden",
        computed_at=_NOW,
    )


def _driver_with_records(records: list[dict[str, Any]]) -> MagicMock:
    """Return a mock driver whose session.run returns *records*."""
    result_mock = AsyncMock()
    result_mock.data = AsyncMock(return_value=records)

    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=result_mock)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return driver


# ---------------------------------------------------------------------------
# test_detect_communities_gds_available
# ---------------------------------------------------------------------------


async def test_detect_communities_gds_available() -> None:
    """When GDS Cypher returns results, build CommunityResult objects from them."""
    gds_records = [
        {"entity_id": "threat-actor--00000000-0000-0000-0000-000000000001", "communityId": 0},
        {"entity_id": "threat-actor--00000000-0000-0000-0000-000000000002", "communityId": 0},
        {"entity_id": "malware--00000000-0000-0000-0000-000000000003", "communityId": 1},
    ]

    result_mock = AsyncMock()
    result_mock.data = AsyncMock(return_value=gds_records)

    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=result_mock)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    detector = CommunityDetector(driver)

    with patch.object(
        detector,
        "_detect_via_gds",
        new=AsyncMock(
            return_value=[
                CommunityResult(
                    community_id=0,
                    entity_ids=[
                        "threat-actor--00000000-0000-0000-0000-000000000001",
                        "threat-actor--00000000-0000-0000-0000-000000000002",
                    ],
                    tenant_id="t1",
                    algorithm="leiden",
                    computed_at=_NOW,
                ),
                CommunityResult(
                    community_id=1,
                    entity_ids=["malware--00000000-0000-0000-0000-000000000003"],
                    tenant_id="t1",
                    algorithm="leiden",
                    computed_at=_NOW,
                ),
            ]
        ),
    ):
        communities = await detector.detect_communities("t1")

    assert len(communities) == 2
    assert communities[0].community_id == 0
    assert len(communities[0].entity_ids) == 2
    assert communities[1].community_id == 1


# ---------------------------------------------------------------------------
# test_detect_communities_fallback
# ---------------------------------------------------------------------------


async def test_detect_communities_fallback() -> None:
    """When GDS raises, fall back to Python connected-components."""
    edges = [
        {"source_id": "a", "target_id": "b"},
        {"source_id": "b", "target_id": "c"},
        {"source_id": "d", "target_id": "d"},  # isolated
    ]
    result_mock = AsyncMock()
    result_mock.data = AsyncMock(return_value=edges)

    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=result_mock)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    detector = CommunityDetector(driver)

    with patch.object(
        detector,
        "_detect_via_gds",
        new=AsyncMock(side_effect=RuntimeError("GDS not available")),
    ):
        communities = await detector.detect_communities("t1")

    all_ids = {eid for c in communities for eid in c.entity_ids}
    assert "a" in all_ids
    assert "b" in all_ids
    assert "c" in all_ids
    # a, b, c should share one community; d alone
    a_community = next(c for c in communities if "a" in c.entity_ids)
    assert "b" in a_community.entity_ids
    assert "c" in a_community.entity_ids


# ---------------------------------------------------------------------------
# test_detect_communities_incremental
# ---------------------------------------------------------------------------


async def test_detect_communities_incremental() -> None:
    """Incremental detection should query only 2-hop neighbors."""
    entity_id = "threat-actor--00000000-0000-0000-0000-000000000001"
    neighbor_id = "malware--00000000-0000-0000-0000-000000000002"

    neighbor_records = [{"nid": neighbor_id}]
    edges = [{"source_id": entity_id, "target_id": neighbor_id}]

    call_count = 0

    async def fake_run(cypher: str, **kwargs: Any) -> AsyncMock:
        nonlocal call_count
        result = AsyncMock()
        if call_count == 0:
            # first call: neighbors query
            result.data = AsyncMock(return_value=neighbor_records)
        else:
            # second call: edge query
            result.data = AsyncMock(return_value=edges)
        call_count += 1
        return result

    session_mock = AsyncMock()
    session_mock.run = fake_run

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    detector = CommunityDetector(driver)
    communities = await detector.detect_communities_for_entity(entity_id, "t1", hop_depth=2)

    assert len(communities) >= 1
    all_ids = {eid for c in communities for eid in c.entity_ids}
    assert entity_id in all_ids
    assert neighbor_id in all_ids


# ---------------------------------------------------------------------------
# test_summarize_community_llm
# ---------------------------------------------------------------------------


async def test_summarize_community_llm() -> None:
    """Summarizer should build a prompt and return the LLM response."""
    community = _make_community(cid=42, n=2)

    entity_records = [
        {"eid": community.entity_ids[0], "name": "APT28", "stype": "threat-actor"},
        {"eid": community.entity_ids[1], "name": "Windows", "stype": "identity"},
    ]
    rel_records = [
        {"src_name": "APT28", "rel_type": "TARGETS", "tgt_name": "Windows"}
    ]

    async def fake_run(cypher: str, **kwargs: Any) -> AsyncMock:
        result = AsyncMock()
        if "name" in cypher.lower() or "stype" in cypher.lower():
            result.data = AsyncMock(return_value=entity_records)
        else:
            result.data = AsyncMock(return_value=rel_records)
        return result

    session_mock = AsyncMock()
    session_mock.run = fake_run

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    summarizer = CommunitySummarizer(driver, ollama_url="http://localhost:11434")

    llm_response = {
        "message": {"content": "APT28 targets Windows infrastructure using spear-phishing."}
    }

    with patch("src.graphrag.summarizer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = llm_response
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        summary = await summarizer.summarize_community(community)

    assert summary.community_id == 42
    assert "APT28" in summary.summary
    assert summary.model_used != "template"


# ---------------------------------------------------------------------------
# test_summarize_community_fallback
# ---------------------------------------------------------------------------


async def test_summarize_community_fallback() -> None:
    """When the LLM call fails, the template fallback should be used."""
    community = _make_community(cid=7, n=4)

    async def fake_run(cypher: str, **kwargs: Any) -> AsyncMock:
        result = AsyncMock()
        result.data = AsyncMock(return_value=[])
        return result

    session_mock = AsyncMock()
    session_mock.run = fake_run

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    summarizer = CommunitySummarizer(driver)

    with patch("src.graphrag.summarizer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("timeout"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        summary = await summarizer.summarize_community(community)

    assert summary.community_id == 7
    assert summary.model_used == "template"
    assert "7" in summary.summary
    assert "4" in summary.summary


# ---------------------------------------------------------------------------
# test_store_summary
# ---------------------------------------------------------------------------


async def test_store_summary() -> None:
    """store_summary_for_community should SET community properties on member nodes."""
    community = _make_community(cid=5, n=2)
    summary = CommunitySummary(
        community_id=5,
        tenant_id="t1",
        summary="Test summary",
        entity_count=2,
        model_used="qwen2.5:3b",
    )

    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=AsyncMock())

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    summarizer = CommunitySummarizer(driver)
    await summarizer.store_summary_for_community(summary, community.entity_ids)

    assert session_mock.run.called
    cypher: str = session_mock.run.call_args.args[0]
    assert "SET" in cypher
    assert "community_id" in cypher
    assert "community_summary" in cypher


# ---------------------------------------------------------------------------
# test_index_full
# ---------------------------------------------------------------------------


async def test_index_full() -> None:
    """index_full should return an IndexingResult with correct counts."""
    communities = [_make_community(0, 3), _make_community(1, 2)]

    detector = AsyncMock(spec=CommunityDetector)
    detector.detect_communities = AsyncMock(return_value=communities)

    summary_mock = CommunitySummary(
        community_id=0,
        tenant_id="t1",
        summary="test",
        entity_count=3,
        model_used="template",
    )

    summarizer = AsyncMock(spec=CommunitySummarizer)
    summarizer.summarize_community = AsyncMock(return_value=summary_mock)
    summarizer.store_summary_for_community = AsyncMock()

    indexer = GraphRAGIndexer(detector, summarizer)
    result = await indexer.index_full("t1")

    assert isinstance(result, IndexingResult)
    assert result.communities_detected == 2
    assert result.summaries_generated == 2
    assert result.incremental is False
    assert result.tenant_id == "t1"


# ---------------------------------------------------------------------------
# test_index_incremental
# ---------------------------------------------------------------------------


async def test_index_incremental() -> None:
    """index_incremental should use detect_communities_for_entity and re-summarize."""
    entity_id = "threat-actor--00000000-0000-0000-0000-000000000001"
    community = _make_community(0, 2)

    detector = AsyncMock(spec=CommunityDetector)
    detector.detect_communities_for_entity = AsyncMock(return_value=[community])

    summary_mock = CommunitySummary(
        community_id=0,
        tenant_id="t1",
        summary="incremental",
        entity_count=2,
        model_used="template",
    )

    summarizer = AsyncMock(spec=CommunitySummarizer)
    summarizer.summarize_community = AsyncMock(return_value=summary_mock)
    summarizer.store_summary_for_community = AsyncMock()

    indexer = GraphRAGIndexer(detector, summarizer)
    result = await indexer.index_incremental(entity_id, "t1")

    detector.detect_communities_for_entity.assert_called_once_with(
        entity_id, "t1", hop_depth=2
    )
    assert result.incremental is True
    assert result.communities_detected == 1
    assert result.summaries_generated == 1


# ---------------------------------------------------------------------------
# test_metrics_populated
# ---------------------------------------------------------------------------


async def test_metrics_populated() -> None:
    """Prometheus counters/histograms should be incremented after indexing."""
    from src.graphrag.indexer import (
        GRAPHRAG_SUMMARIES_UPDATED,
        GRAPHRAG_UPDATE_FREQUENCY,
    )

    community = _make_community(0, 1, tenant_id="tenant-metrics")

    detector = AsyncMock(spec=CommunityDetector)
    detector.detect_communities = AsyncMock(return_value=[community])

    summary_mock = CommunitySummary(
        community_id=0,
        tenant_id="tenant-metrics",
        summary="metrics test",
        entity_count=1,
        model_used="template",
    )

    summarizer = AsyncMock(spec=CommunitySummarizer)
    summarizer.summarize_community = AsyncMock(return_value=summary_mock)
    summarizer.store_summary_for_community = AsyncMock()

    indexer = GraphRAGIndexer(detector, summarizer)

    before_freq = GRAPHRAG_UPDATE_FREQUENCY.labels(
        tenant_id="tenant-metrics"
    )._value.get()
    before_summaries = GRAPHRAG_SUMMARIES_UPDATED.labels(
        tenant_id="tenant-metrics"
    )._value.get()

    await indexer.index_full("tenant-metrics")

    after_freq = GRAPHRAG_UPDATE_FREQUENCY.labels(
        tenant_id="tenant-metrics"
    )._value.get()
    after_summaries = GRAPHRAG_SUMMARIES_UPDATED.labels(
        tenant_id="tenant-metrics"
    )._value.get()

    assert after_freq > before_freq
    assert after_summaries > before_summaries


# ---------------------------------------------------------------------------
# test_python_connected_components_utility
# ---------------------------------------------------------------------------


def test_connected_components_basic() -> None:
    """The utility function should assign same ID to connected nodes."""
    edges = [("a", "b"), ("b", "c"), ("d", "e")]
    assignment = _connected_components(edges)

    assert assignment["a"] == assignment["b"] == assignment["c"]
    assert assignment["d"] == assignment["e"]
    assert assignment["a"] != assignment["d"]
