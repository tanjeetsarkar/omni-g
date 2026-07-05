from __future__ import annotations

from celery import Celery

from .config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "processor",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["src.processor.tasks"],
    )
    app.conf.update(
        task_default_queue=settings.celery_task_queue,
        task_always_eager=settings.celery_task_always_eager,
        task_ignore_result=settings.celery_task_ignore_result,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        broker_connection_retry_on_startup=True,
    )
    return app


celery_app = create_celery_app()
