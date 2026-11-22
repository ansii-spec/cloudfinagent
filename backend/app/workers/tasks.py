import uuid

from app.db import SessionLocal
from app.workers.celery_app import celery


@celery.task(name="app.workers.tasks.run_scan")
def run_scan(scan_id: str):
    from app.services import scan_service
    scan_service.run_scan(uuid.UUID(str(scan_id)))


@celery.task(name="app.workers.tasks.execute_action")
def execute_action(action_id: str):
    from app.services import remediation_service
    remediation_service.execute(uuid.UUID(str(action_id)))


@celery.task(name="app.workers.tasks.accrue_savings")
def accrue_savings():
    from app.services import savings_service
    with SessionLocal() as db:
        return savings_service.accrue(db)


@celery.task(name="app.workers.tasks.reconcile")
def reconcile():
    from app.services import savings_service
    with SessionLocal() as db:
        return savings_service.reconcile(db)


@celery.task(name="app.workers.tasks.scheduled_scans")
def scheduled_scans():
    from app.services import scan_service
    return scan_service.scheduled_scans()
