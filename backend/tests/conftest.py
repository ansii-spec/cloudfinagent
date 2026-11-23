import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db", "REDIS_URL": "redis://127.0.0.1:1/0",
    "CELERY_EAGER": "true", "WAITER_DELAY_S": "0", "WAITER_MAX_ATTEMPTS": "3",
    "SECRET_KEY": "test-secret-key-test-secret-key-0123", "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.cache import MemoryCache, set_cache  # noqa: E402
from app.db import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401
from app.main import create_app  # noqa: E402

H = {"X-Requested-With": "ec2opt"}


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    set_cache(MemoryCache())
    yield


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def client():
    return TestClient(create_app())


def register(client, email="ann@example.com", name="Ann"):
    r = client.post("/api/v1/auth/register", json={"name": name, "email": email, "password": "CorrectHorse1"},
                    headers=H)
    assert r.status_code == 201, r.text
    return r.json()
