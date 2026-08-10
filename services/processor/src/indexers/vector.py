"""Dense embedding indexer for ContextUnit nodes in Qdrant (Phase 4).

The indexer is provider-aware: when ``LLM_PROVIDER=openrouter`` it generates
embeddings via the unified :class:`~processor.llm.client.LLMClient` (remote
OpenRouter embeddings API); otherwise it falls back to the local BGE-M3 model
loaded via ``FlagEmbedding``. This keeps the ContextUnit indexing path aligned
with the configured LLM/embedding provider instead of always loading BGE-M3
locally.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..llm.client import LLMClient
    from ..processor.config import Settings


class ContextUnitIndexer:
    """Encodes ContextUnit text and upserts dense vectors to Qdrant.

    Provider selection:

    * ``LLM_PROVIDER=openrouter`` → remote embeddings via
      :class:`~processor.llm.client.LLMClient` (model =
      ``OPENROUTER_EMBEDDING_MODEL``). The embedding dimension is auto-detected
      from the first remote response and used for Qdrant collection creation,
      overriding ``EMBEDDING_DIM``.
    * otherwise (``ollama`` / local) → local BGE-M3 via ``FlagEmbedding``.
      Model, dimension, and FP16 mode are configurable via
      :class:`~processor.config.Settings` (``EMBEDDING_MODEL_NAME``,
      ``EMBEDDING_DIM``, ``EMBEDDING_USE_FP16`` env vars). Defaults to
      ``BAAI/bge-m3``, 1024-dim, FP16 enabled.

    The local BGE-M3 model and the remote LLM client are both lazy-loaded on
    first use to avoid slow startup times. Collection name convention:
    ``context_units_{tenant_id}``.
    """

    def __init__(
        self,
        qdrant_url: str,
        api_key: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        from ..processor.config import get_settings

        self._qdrant_url = qdrant_url
        self._api_key = api_key
        self._model: Any = None
        self._qdrant: Any = None
        self._llm_client: LLMClient | None = None
        self._remote_dim: int | None = None

        _cfg = settings or get_settings()
        self._provider: str = _cfg.llm_provider.lower()
        self._embedding_model: str = _cfg.embedding_model
        self._embedding_dim: int = _cfg.embedding_dim
        self._embedding_use_fp16: bool = _cfg.embedding_use_fp16

    def _get_llm_client(self) -> LLMClient:
        if self._llm_client is None:
            from ..llm.client import LLMClient

            self._llm_client = LLMClient()
            logger.info(
                "ContextUnitIndexer using remote embeddings",
                extra={"provider": self._provider},
            )
        return self._llm_client

    def _get_model(self) -> Any:
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-untyped]

            self._model = BGEM3FlagModel(self._embedding_model, use_fp16=self._embedding_use_fp16)
            logger.info("BGE-M3 model loaded", extra={"model": self._embedding_model})
        return self._model

    def _get_qdrant(self) -> Any:
        if self._qdrant is None:
            from qdrant_client import AsyncQdrantClient  # type: ignore[import-untyped]

            self._qdrant = AsyncQdrantClient(url=self._qdrant_url, api_key=self._api_key)
        return self._qdrant

    async def encode(self, texts: list[str]) -> list[list[float]]:
        """Return dense embeddings (list of float vectors) for *texts*.

        Uses the remote LLM provider when ``LLM_PROVIDER=openrouter``; otherwise
        falls back to the local BGE-M3 model. Remote embeddings are requested
        concurrently (bounded by a small semaphore) since the LLM client exposes
        a single-text ``embed`` API.
        """
        if not texts:
            return []

        if self._provider == "openrouter":
            return await self._encode_remote(texts)
        return self._encode_local(texts)

    async def _encode_remote(self, texts: list[str]) -> list[list[float]]:
        client = self._get_llm_client()
        sem = asyncio.Semaphore(8)

        async def _embed_one(text: str) -> list[float]:
            async with sem:
                return await client.embed(text)

        vectors = await asyncio.gather(*(_embed_one(t) for t in texts))

        # Auto-detect remote embedding dimension on first successful call
        if self._remote_dim is None:
            for v in vectors:
                if v:
                    self._remote_dim = len(v)
                    logger.info(
                        "Remote embedding dimension detected",
                        extra={"dim": self._remote_dim},
                    )
                    break
        return vectors

    def _encode_local(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._get_model().encode(texts, batch_size=12)["dense_vecs"]
        return [row.tolist() for row in embeddings]

    async def _ensure_collection(self, tenant_id: str) -> None:
        from qdrant_client.models import Distance, VectorParams  # type: ignore[import-untyped]

        collection = f"context_units_{tenant_id}"
        client = self._get_qdrant()
        try:
            existing = await client.get_collections()
            names = {c.name for c in existing.collections}
            if collection not in names:
                await client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=self._effective_dim(), distance=Distance.COSINE),
                )
                logger.info("qdrant_collection_created", extra={"collection": collection})
        except Exception:
            logger.exception("ensure_collection_failed", extra={"collection": collection})
            raise

    def _effective_dim(self) -> int:
        """Return the embedding dimension used for Qdrant collection creation.

        For the remote (OpenRouter) provider, the dimension is auto-detected from
        the first embedding response (``_remote_dim``). Until that first response
        is available, fall back to the configured ``EMBEDDING_DIM``. For the local
        BGE-M3 path, the configured ``EMBEDDING_DIM`` is authoritative.
        """
        if self._provider == "openrouter" and self._remote_dim is not None:
            return self._remote_dim
        return self._embedding_dim

    async def upsert_to_qdrant(
        self,
        context_id: str,
        text: str,
        payload: dict[str, Any],
        tenant_id: str,
    ) -> None:
        """Encode *text* and upsert the vector to Qdrant."""
        from qdrant_client.models import PointStruct  # type: ignore[import-untyped]

        try:
            embeddings = await self.encode([text])
            vector: list[float] = embeddings[0]

            await self._ensure_collection(tenant_id)

            # Qdrant point IDs must be unsigned integers — derive from context_id hash
            point_id = int(hashlib.sha256(context_id.encode()).hexdigest()[:15], 16)

            await self._get_qdrant().upsert(
                collection_name=f"context_units_{tenant_id}",
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "context_id": context_id,
                            "tenant_id": tenant_id,
                            **payload,
                        },
                    )
                ],
            )
            logger.debug("context_unit_indexed", extra={"context_id": context_id})
        except Exception:
            logger.exception("context_unit_index_failed", extra={"context_id": context_id})

    async def search(
        self,
        query: str,
        tenant_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return top-N ContextUnit payloads matching *query* in the tenant collection."""
        collection_name = f"context_units_{tenant_id}"
        try:
            client = self._get_qdrant()
            try:
                exists = await client.collection_exists(collection_name)
            except Exception:
                logger.warning(
                    "qdrant_collection_exists_failed",
                    extra={"collection": collection_name, "tenant_id": tenant_id},
                )
                exists = False

            if not exists:
                logger.debug(
                    "context_units_fallback_collection_missing",
                    extra={"collection": collection_name, "tenant_id": tenant_id},
                )
                return []

            embeddings = await self.encode([query])
            vector: list[float] = embeddings[0]
            hits = await client.search(
                collection_name=collection_name,
                query_vector=vector,
                limit=limit,
            )
            return [{"context_id": h.payload.get("context_id", ""), "score": h.score, **h.payload} for h in hits if h.payload]
        except Exception:
            logger.exception("context_unit_search_failed", extra={"tenant_id": tenant_id})
            return []

    async def close(self) -> None:
        if self._qdrant is not None:
            await self._qdrant.close()
            self._qdrant = None
