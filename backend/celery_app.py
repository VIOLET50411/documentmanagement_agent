"""
Celery Application Configuration
"""

from celery import Celery
from celery.schedules import crontab
from kombu import Queue
from app.config import settings

celery = Celery(
    "docmind",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_acks_late=True,  # Task only removed from queue after completion
    worker_prefetch_multiplier=1,  # Fair distribution, prevents memory spikes
    task_track_started=True,
    result_expires=3600,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    task_default_queue=settings.celery_default_queue,
    task_queues=(
        Queue(settings.celery_default_queue),
        Queue(settings.celery_ingestion_queue),
        Queue(settings.celery_reindex_queue),
        Queue(settings.celery_maintenance_queue),
    ),
    task_routes={
        "app.ingestion.tasks.process_document": {"queue": settings.celery_ingestion_queue},
        "app.maintenance.tasks.runtime_maintenance_job": {"queue": settings.celery_maintenance_queue},
        "app.evaluation.tasks.run_evaluation_job": {"queue": settings.celery_maintenance_queue},
    },
    beat_schedule={
        "runtime-maintenance-hourly": {
            "task": "app.maintenance.tasks.runtime_maintenance_job",
            "schedule": crontab(minute=15),  # every hour at xx:15
            "kwargs": {"cleanup_empty": True},
        }
    },
)

# Auto-discover tasks
celery.autodiscover_tasks(["app.ingestion", "app.maintenance", "app.evaluation"])
