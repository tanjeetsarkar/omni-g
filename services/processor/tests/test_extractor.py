"""Tests for ZeroMemExtractor entity filtering (Issue 2 — irrelevant numeric/temporal entities)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from src.extractors.zeromem_extractor import (
    _NON_ALPHABETIC_RE,
    _SPACY_ALLOWED_LABELS,
    ZeroMemExtractor,
)

# ——— Fake spaCy ents for testing ——————————————————————————————————————————


@dataclass
class _FakeSpan:
    text: str
    label_: str
    start_char: int = 0
    end_char: int = 0


class _FakeDoc:
    def __init__(self, ents: list[_FakeSpan]) -> None:
        self.ents = ents


class _FakeNLP:
    def __init__(self, ents: list[_FakeSpan] | None = None) -> None:
        self._ents = ents or []

    def __call__(self, text: str) -> _FakeDoc:  # noqa: ARG002
        return _FakeDoc(self._ents)


class _FakeGLiNER:
    def predict_entities(self, text: str, labels: list[str], threshold: float = 0.5) -> list[dict[str, Any]]:
        return []


def _make_extractor(
    spacy_allowed_labels: frozenset[str] | None = None,
    min_entity_length: int = 2,
) -> ZeroMemExtractor:
    return ZeroMemExtractor(
        spacy_allowed_labels=spacy_allowed_labels,
        min_entity_length=min_entity_length,
    )


# ——— Tests ——————————————————————————————————————————————————————————————————


class TestExtractorFiltering:
    def test_allowed_labels_pass_through(self) -> None:
        extractor = _make_extractor()
        fake_nlp = _FakeNLP([_FakeSpan("Narendra Modi", "PERSON"), _FakeSpan("Kolkata", "GPE")])
        with (
            patch.object(extractor, "_get_nlp", return_value=fake_nlp),
            patch.object(extractor, "_get_gliner", return_value=_FakeGLiNER()),
        ):
            result = extractor.extract("Narendra Modi visited Kolkata", "ctx-1", "t1")
        names = {e.name for e in result.entities}
        assert "Narendra Modi" in names
        assert "Kolkata" in names
        assert len(result.entities) == 2

    def test_cardinal_ordinal_percent_dropped(self) -> None:
        extractor = _make_extractor()
        fake_nlp = _FakeNLP(
            [
                _FakeSpan("50,000", "CARDINAL"),
                _FakeSpan("1", "CARDINAL"),
                _FakeSpan("first", "ORDINAL"),
                _FakeSpan("50%", "PERCENT"),
                _FakeSpan("$1,000", "MONEY"),
                _FakeSpan("10 kg", "QUANTITY"),
                _FakeSpan("3pm", "TIME"),
                _FakeSpan("January 2026", "DATE"),
            ]
        )
        with (
            patch.object(extractor, "_get_nlp", return_value=fake_nlp),
            patch.object(extractor, "_get_gliner", return_value=_FakeGLiNER()),
        ):
            result = extractor.extract("stats with numbers", "ctx-2", "t1")
        assert len(result.entities) == 0, f"Expected 0 entities but got: {[e.name for e in result.entities]}"

    def test_short_entity_dropped(self) -> None:
        extractor = _make_extractor(min_entity_length=2)
        fake_nlp = _FakeNLP([_FakeSpan("US", "GPE"), _FakeSpan("A", "ORG"), _FakeSpan("1", "CARDINAL")])
        with (
            patch.object(extractor, "_get_nlp", return_value=fake_nlp),
            patch.object(extractor, "_get_gliner", return_value=_FakeGLiNER()),
        ):
            result = extractor.extract("US and A", "ctx-3", "t1")
        names = {e.name for e in result.entities}
        assert "US" in names
        assert "A" not in names

    def test_pure_numeric_name_dropped(self) -> None:
        extractor = _make_extractor()
        fake_nlp = _FakeNLP([_FakeSpan("50500", "ORG")])
        with (
            patch.object(extractor, "_get_nlp", return_value=fake_nlp),
            patch.object(extractor, "_get_gliner", return_value=_FakeGLiNER()),
        ):
            result = extractor.extract("code 50500", "ctx-4", "t1")
        assert len(result.entities) == 0

    def test_punctuation_only_name_dropped(self) -> None:
        extractor = _make_extractor()
        fake_nlp = _FakeNLP([_FakeSpan("$$$", "ORG")])
        with (
            patch.object(extractor, "_get_nlp", return_value=fake_nlp),
            patch.object(extractor, "_get_gliner", return_value=_FakeGLiNER()),
        ):
            result = extractor.extract("$$$", "ctx-5", "t1")
        assert len(result.entities) == 0

    def test_env_label_override(self) -> None:
        custom = frozenset({"PERSON", "ORG"})
        extractor = _make_extractor(spacy_allowed_labels=custom)
        fake_nlp = _FakeNLP([_FakeSpan("Modi", "PERSON"), _FakeSpan("Delhi", "GPE")])
        with (
            patch.object(extractor, "_get_nlp", return_value=fake_nlp),
            patch.object(extractor, "_get_gliner", return_value=_FakeGLiNER()),
        ):
            result = extractor.extract("Modi in Delhi", "ctx-6", "t1")
        names = {e.name for e in result.entities}
        assert "Modi" in names
        assert "Delhi" not in names, "GPE should be dropped from custom allowlist"

    def test_gliner_not_affected_by_spacy_filter(self) -> None:
        extractor = _make_extractor()

        class _ActiveGLiNER:
            def predict_entities(self, text: str, labels: list[str], threshold: float = 0.5) -> list[dict[str, Any]]:
                return [{"text": "topic", "label": "topic", "score": 0.85, "start": 0, "end": 5}]

        with (
            patch.object(extractor, "_get_nlp", return_value=_FakeNLP()),
            patch.object(extractor, "_get_gliner", return_value=_ActiveGLiNER()),
        ):
            result = extractor.extract("Some text about a topic", "ctx-7", "t1")
        assert len(result.entities) == 1
        assert result.entities[0].name == "topic"
        assert result.entities[0].type == "TOPIC"

    def test_default_allowlist_excludes_non_entity_labels(self) -> None:
        for bad_label in ("CARDINAL", "ORDINAL", "PERCENT", "MONEY", "QUANTITY", "TIME", "DATE"):
            assert bad_label not in _SPACY_ALLOWED_LABELS, f"{bad_label} should NOT be in the default allowlist"

    def test_non_alphabetic_regex(self) -> None:
        assert _NON_ALPHABETIC_RE.match("50,000") is not None
        assert _NON_ALPHABETIC_RE.match("1") is not None
        assert _NON_ALPHABETIC_RE.match("$1,000") is not None
        assert _NON_ALPHABETIC_RE.match("$$$") is not None
        assert _NON_ALPHABETIC_RE.match("Modi") is None
        assert _NON_ALPHABETIC_RE.match("Kolkata") is None
        assert _NON_ALPHABETIC_RE.match("US") is None
