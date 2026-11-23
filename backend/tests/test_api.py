"""REST API: auth, CSRF, the real connection wizard (verified against moto), disconnect and tenancy isolation."""
import pytest
from moto import mock_aws

from tests.conftest import H, register

API = "/api/v1"
ARN = "arn:aws:iam::111122223333:role/EC2OptimizerAccessRole"


@pytest.fixture
def aws():
    with mock_aws():
        yield


def connect(client, label="Prod", enable_actions=False):
    w = client.post(f"{API}/connections", json={"label": label, "enable_actions": enable_actions}, headers=H)
    assert w.status_code == 201, w.text
    w = w.json()
    ok = client.post(f"{API}/connections/{w['id']}/verify", json={"role_arn": ARN}, headers=H)
    assert ok.status_code == 200 and ok.json()["status"] == "connected", ok.text
    return w


def test_auth_flow(client):
    register(client)
    assert client.get(f"{API}/auth/me").json()["email"] == "ann@example.com"
    assert client.post(f"{API}/auth/logout", headers=H).status_code == 204
    client.cookies.clear()
    assert client.get(f"{API}/auth/me").status_code == 401
    bad = client.post(f"{API}/auth/login", json={"email": "ann@example.com", "password": "wrongwrong"}, headers=H)
    assert bad.status_code == 401 and bad.json()["error"]["message"] == "Invalid email or password"
    ok = client.post(f"{API}/auth/login", json={"email": "ANN@example.com", "password": "CorrectHorse1"}, headers=H)
    assert ok.status_code == 200


def test_short_password_rejected(client):
    r = client.post(f"{API}/auth/register", json={"name": "x", "email": "a@b.co", "password": "short"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_rate_limited(client):
    register(client)
    codes = [client.post(f"{API}/auth/login", json={"email": "ann@example.com", "password": "nopenopenope"},
                         headers=H).status_code for _ in range(6)]
    assert codes[-1] == 429


def test_csrf_header_required(client):
    r = client.post(f"{API}/auth/register", json={"name": "x", "email": "a@b.co", "password": "longenough1"})
    assert r.status_code == 403


def test_no_demo_endpoints(client):
    register(client)
    assert client.post(f"{API}/connections/demo", headers=H).status_code in (404, 405)
    assert "demo_mode" not in client.get(f"{API}/config/public").json()


def test_connection_wizard_and_disconnect(client, aws):
    register(client)
    w = client.post(f"{API}/connections", json={"label": "Prod", "enable_actions": False}, headers=H).json()
    assert len(w["external_id"]) >= 24 and "quickcreate" in w["cloudformation_quick_create_url"]
    assert "sts:ExternalId" in str(w["manual_trust_policy_json"])
    # each connection gets its own role / stack name so a leftover role never blocks a reconnect
    assert w["role_name"].startswith("EC2OptimizerAccessRole-") and w["stack_name"].startswith("EC2OptimizerAccess-")
    assert f"param_RoleName={w['role_name']}" in w["cloudformation_quick_create_url"]
    bad = client.post(f"{API}/connections/{w['id']}/verify", json={"role_arn": "nope"}, headers=H)
    assert bad.status_code == 422
    ok = client.post(f"{API}/connections/{w['id']}/verify", json={"role_arn": ARN}, headers=H).json()
    assert ok["status"] == "connected"
    r = client.delete(f"{API}/connections/{w['id']}", headers=H)
    assert r.status_code == 200
    cleanup = r.json()["aws_cleanup"]
    assert cleanup["stack_name"] and cleanup["console_url"].startswith("https://console.aws.amazon.com/cloudformation")
    assert client.get(f"{API}/connections").json() == []


def test_reconnect_gets_new_role_name(client):
    register(client)
    a = client.post(f"{API}/connections", json={"label": "A"}, headers=H).json()
    client.delete(f"{API}/connections/{a['id']}", headers=H)
    b = client.post(f"{API}/connections", json={"label": "B"}, headers=H).json()
    assert a["role_name"] != b["role_name"] and a["stack_name"] != b["stack_name"]


def test_tenancy_isolation(client, aws):
    register(client)
    conn = connect(client)
    client.cookies.clear()
    register(client, email="bob@example.com", name="Bob")
    assert client.get(f"{API}/connections/{conn['id']}").status_code == 404
    assert client.get(f"{API}/findings", params={"connection_id": conn["id"]}).status_code == 404
    assert client.delete(f"{API}/connections/{conn['id']}", headers=H).status_code == 404
