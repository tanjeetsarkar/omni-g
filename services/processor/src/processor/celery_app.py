from __future__ import annotations

from typing import Any

from celery import Celery

from .config import Settings, get_settings


def _build_briefing_beat_schedule(settings: Settings) -> dict[str, Any]:
    """Return a Celery Beat schedule with one daily entry per configured tenant.

    Each entry runs ``processor.generate_briefing`` at ``BRIEFING_HOUR:00 UTC``
    for one tenant.  The schedule is keyed as ``briefing-{tenant_id}-daily``.
    """
    from celery.schedules import crontab

    schedule: dict[str, Any] = {}
    tenant_ids = [t.strip() for t in settings.briefing_tenants.split(",") if t.strip()]
    for tenant_id in tenant_ids:
        schedule[f"briefing-{tenant_id}-daily"] = {
            "task": "processor.generate_briefing",
            "schedule": crontab(hour=settings.briefing_hour, minute=0),
            "args": (tenant_id,),
        }
    return schedule


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
    if settings.celery_briefing_enabled:
        app.conf.beat_schedule = _build_briefing_beat_schedule(settings)
        app.conf.timezone = "UTC"
    return app


celery_app = create_celery_app()
