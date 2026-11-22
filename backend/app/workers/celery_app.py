from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

s = get_settings()
celery = Celery("ec2opt", broker=s.redis_url, backend=s.redis_url, include=["app.workers.tasks"])
celery.conf.update(
    task_always_eager=s.celery_eager,
    task_eager_propagates=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    beat_schedule={
        "accrue-savings": {"task": "app.workers.tasks.accrue_savings", "schedule": crontab(hour=0, minute=10)},
        "reconcile": {"task": "app.workers.tasks.reconcile", "schedule": crontab(hour=2, minute=0)},
        "scheduled-scans": {"task": "app.workers.tasks.scheduled_scans", "schedule": crontab(hour=3, minute=0)},
    },
)
