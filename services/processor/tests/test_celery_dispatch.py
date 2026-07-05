from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.processor import main as processor_main
from src.processor import tasks as processor_tasks
from src.processor.config import Settings


class _DispatchingConsumer:
    def __init__(self) -> None:
        self.started = False
        self.process_messages_calls = 0

    def start(self) -> None:
        self.started = True

    async def process_messages(self, handler: Any) -> None:
        self.process_messages_calls += 1
        await handler({"id": "evt-001", "tenant_id": "default", "payload": {"text": "hello"}})
        raise asyncio.CancelledError()


@pytest.mark.asyncio
async def test_startup_consumer_dispatches_celery_task_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        LOG_LEVEL="debug",
        HTTP_PORT=8001,
        KAFKA_ENABLED=True,
        KAFKA_BROKERS="localhost:9092",
        CELERY_ENABLED=True,
        CELERY_TASK_ALWAYS_EAGER=True,
        REDIS_URL="redis://localhost:6379",
        NEO4J_URL="neo4j://localhost:7687",
        NEO4J_USER="neo4j",
        QDRANT_URL="http://localhost:6333",
        OLLAMA_URL="http://localhost:11434",
    )

    consumer = _DispatchingConsumer()
    dispatched_events: list[dict[str, Any]] = []

    def fake_raw_consumer(**kwargs: Any) -> _DispatchingConsumer:
        return consumer

    def fake_enqueue_process_event(event: dict[str, Any]) -> str:
        dispatched_events.append(event)
        return "task-123"

    runtime_create = AsyncMock(
        side_effect=AssertionError("ProcessorRuntime.create should not run when Celery is enabled")
    )

    monkeypatch.setattr("src.kafka.consumer.RawEventConsumer", fake_raw_consumer)
    monkeypatch.setattr("src.processor.tasks.enqueue_process_event", fake_enqueue_process_event)
    monkeypatch.setattr("src.processor.runtime.ProcessorRuntime.create", runtime_create)

    with pytest.raises(asyncio.CancelledError):
        await processor_main.startup_consumer(settings, worker_id=7)

    assert consumer.started is True
    assert consumer.process_messages_calls == 1
    runtime_create.assert_not_awaited()
    assert dispatched_events == [
        {"id": "evt-001", "tenant_id": "default", "payload": {"text": "hello"}}
    ]


# ---------------------------------------------------------------------------
# process_event_task: worker-level persistent runtime lifecycle
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_worker_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level worker singletons before every test in this module."""
    monkeypatch.setattr(processor_tasks, "_worker_loop", None)
    monkeypatch.setattr(processor_tasks, "_worker_runtime", None)


def _fake_runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.process_event = AsyncMock()
    runtime.close = AsyncMock()
    return runtime


def test_process_event_task_calls_runtime_process_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_event delegates to runtime.process_event with the raw event dict."""
    runtime = _fake_runtime()

    with patch.object(processor_tasks, "_get_worker_runtime", return_value=runtime):
        result = processor_tasks._run_event(
            {"id": "evt-abc", "tenant_id": "default", "payload": {"text": "hello"}},
        )

    runtime.process_event.assert_awaited_once_with(
        {"id": "evt-abc", "tenant_id": "default", "payload": {"text": "hello"}}
    )
    assert result == {"status": "processed", "event_id": "evt-abc"}


def test_process_event_task_reuses_runtime_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime is initialised only once and reused on the second call."""
    runtime = _fake_runtime()
    create_calls: list[int] = []

    async def fake_create(cfg: Any, *, worker_id: int) -> MagicMock:
        create_calls.append(1)
        return runtime

    monkeypatch.setattr("src.processor.runtime.ProcessorRuntime.create", fake_create)

    event = {"id": "evt-1", "payload": {"text": "first"}}
    processor_tasks._run_event(event)
    processor_tasks._run_event(event)

    assert len(create_calls) == 1, "Runtime should be created only once per worker"
    assert runtime.process_event.await_count == 2


def test_process_event_task_resets_runtime_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On failure the runtime is torn down so the next retry starts with fresh connections."""
    runtime = _fake_runtime()
    runtime.process_event = AsyncMock(side_effect=RuntimeError("neo4j down"))

    # Seed the module-level runtime so _get_worker_runtime() returns it
    # without real connections, and so the cleanup path is exercised.
    monkeypatch.setattr(processor_tasks, "_worker_runtime", runtime)

    with pytest.raises(RuntimeError):
        processor_tasks._run_event({"id": "evt-fail", "payload": {"url": "x"}})

    # Runtime must have been closed and cleared
    runtime.close.assert_awaited_once()
    assert processor_tasks._worker_runtime is None
