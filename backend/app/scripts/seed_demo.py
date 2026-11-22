"""Creates demo@example.com / DemoPass123! with a connected demo account, a finished scan and ~60 days of
savings history.   docker compose exec api python -m app.scripts.seed_demo"""
from sqlalchemy import select

from app.config import get_settings
from app.core.security import hash_password
from app.db import SessionLocal
from app.models import User
from app.services import demo_service, scan_service

EMAIL, PASSWORD = "demo@example.com", "DemoPass123!"


def main():
    if not get_settings().demo_mode:
        raise SystemExit("seed_demo only runs with DEMO_MODE=true")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == EMAIL))
        if user is None:
            user = User(email=EMAIL, name="Demo User", password_hash=hash_password(PASSWORD))
            db.add(user)
            db.commit()
        conn = demo_service.create_demo_connection(db, user)
        try:
            scan = scan_service.start_scan(db, conn, None)
            print(f"scan queued: {scan.id}")
        except Exception as e:  # noqa: BLE001 - already running
            print(f"scan not started: {e}")
    print(f"demo user ready: {EMAIL} / {PASSWORD}")


if __name__ == "__main__":
    main()
