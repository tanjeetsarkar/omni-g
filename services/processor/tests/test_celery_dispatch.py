from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.processor import main as processor_main
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
