"""BGE-M3 dense embedding indexer for ContextUnit nodes in Qdrant (Phase 4)."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

# BGE-M3 dense embedding dimension
_EMBEDDING_DIM = 1024

if TYPE_CHECKING:
    pass


class ContextUnitIndexer:
    """Encodes ContextUnit text with BGE-M3 and upserts dense vectors to Qdrant.

    The BGE-M3 model is lazy-loaded on first use to avoid slow startup times.
    Collection name convention: ``context_units_{tenant_id}``.
    """

    def __init__(self, qdrant_url: str, api_key: str | None = None) -> None:
        self._qdrant_url = qdrant_url
        self._api_key = api_key
        self._model: Any = None
        self._qdrant: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-untyped]

            self._model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
            logger.info("BGE-M3 model loaded")
        return self._model

    def _get_qdrant(self) -> Any:
        if self._qdrant is None:
            from qdrant_client import AsyncQdrantClient  # type: ignore[import-untyped]

            self._qdrant = AsyncQdrantClient(url=self._qdrant_url, api_key=self._api_key)
        return self._qdrant

    def encode(self, texts: list[str]) -> Any:
        """Return dense embeddings (ndarray shape [N, 1024]) for *texts*."""
        return self._get_model().encode(texts, batch_size=12)["dense_vecs"]

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
                    vectors_config=VectorParams(size=_EMBEDDING_DIM, distance=Distance.COSINE),
                )
                logger.info("qdrant_collection_created", extra={"collection": collection})
        except Exception:
            logger.exception("ensure_collection_failed", extra={"collection": collection})
            raise

    async def upsert_to_qdrant(
        self,
        context_id: str,
        text: str,
        payload: dict[str, Any],
        tenant_id: str,
    ) -> None:
        """Encode *text* with BGE-M3 and upsert the vector to Qdrant."""
        from qdrant_client.models import PointStruct  # type: ignore[import-untyped]

        try:
            embeddings = self.encode([text])
            vector: list[float] = embeddings[0].tolist()

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

            embeddings = self.encode([query])
            vector: list[float] = embeddings[0].tolist()
            hits = await client.search(
                collection_name=collection_name,
                query_vector=vector,
                limit=limit,
            )
            return [
                {"context_id": h.payload.get("context_id", ""), "score": h.score, **h.payload}
                for h in hits
                if h.payload
            ]
        except Exception:
            logger.exception("context_unit_search_failed", extra={"tenant_id": tenant_id})
            return []

    async def close(self) -> None:
        if self._qdrant is not None:
            await self._qdrant.close()
            self._qdrant = None
