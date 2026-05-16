from __future__ import annotations

import logging
from typing import Any

from ..models.stix import ExtractionResult

logger = logging.getLogger(__name__)


class LLMExtractor:
    """
    Extracts STIX entities from raw text using an LLM.

    Phase M3.3 implementation will wire this to Ollama via the `instructor`
    library for structured output. This skeleton provides the interface.
    """

    def __init__(self, ollama_url: str, model: str = "qwen2.5:3b") -> None:
        self._ollama_url = ollama_url
        self._model = model

    async def extract(
        self, event_id: str, text: str, metadata: dict[str, Any] | None = None
    ) -> ExtractionResult:
        """
        Extract STIX entities from text.

        Returns an ExtractionResult with zero entities and zero confidence until
        Phase M3.3 wires up the real LLM call.
        """
        logger.debug(
            "LLM extraction requested",
            extra={"event_id": event_id, "model": self._model},
        )
        # TODO(M3.3): replace with real instructor + Ollama call
        return ExtractionResult(
            source_event_id=event_id,
            extraction_confidence=0.0,
        )
