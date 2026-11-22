"""End-to-end through the REST API in DEMO_MODE: register -> demo connection -> scan -> findings ->
preview -> apply -> undo -> savings. Also auth, CSRF and tenancy isolation."""
from tests.conftest import H, register

API = "/api/v1"


def demo(client):
    register(client)
    r = client.post(f"{API}/connections/demo", headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def findings(client, cid, **params):
    r = client.get(f"{API}/findings", params={"connection_id": cid, "page_size": 100, **params})
    assert r.status_code == 200, r.text
    return r.json()


def by_name(client, cid, name):
    return next(f for f in findings(client, cid)["items"] if f["name"] == name)


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


def test_demo_scan_findings(client):
    conn = demo(client)
    scan = client.get(f"{API}/scans/{conn['scan_id']}").json()
    assert scan["status"] == "completed" and scan["progress"]["processed"] == 14
    data = findings(client, conn["id"])
    statuses = {f["status"] for f in data["items"]}
    assert {"IDLE", "OVER_PROVISIONED", "UNDER_PROVISIONED", "NEEDS_REVIEW", "ACTIVE", "STOPPED",
            "INSUFFICIENT_DATA"} <= statuses
    assert data["items"][0]["status"] == "IDLE"          # severity sort
    assert data["summary"]["potential_monthly_saving"] > 0
    only_over = findings(client, conn["id"], status="OVER_PROVISIONED")["items"]
    assert only_over and all(f["status"] == "OVER_PROVISIONED" for f in only_over)
    detail = client.get(f"{API}/findings/{by_name(client, conn['id'], 'reporting-worker')['id']}").json()
    assert detail["evidence_steps"] and detail["hourly_series"] and detail["suggestion"]["to_type"] == "m5.large"


def test_apply_resize_then_undo(client):
    conn = demo(client)
    f = by_name(client, conn["id"], "reporting-worker")
    pv = client.post(f"{API}/findings/{f['id']}/actions/preview", json={"action": "RESIZE"}, headers=H).json()
    assert pv["blockers"] == [] and pv["change"] == {"from": "m5.2xlarge", "to": "m5.large"}
    assert pv["cost"]["monthly_delta"] < 0
    r = client.post(f"{API}/findings/{f['id']}/actions", json={"action": "RESIZE", "options": {}}, headers=H)
    assert r.status_code == 202, r.text
    a = client.get(f"{API}/actions/{r.json()['action_id']}").json()
    assert a["status"] == "succeeded" and a["after"]["instance_type"] == "m5.large" and a["can_undo"]
    assert a["savings_active"] and a["monthly_saving_usd"] > 0
    summ = client.get(f"{API}/dashboard/summary", params={"connection_id": conn["id"]}).json()
    assert summ["realized"]["monthly_run_rate"] > 0
    u = client.post(f"{API}/actions/{a['id']}/undo", headers=H)
    assert u.status_code == 202, u.text
    child = client.get(f"{API}/actions/{u.json()['action_id']}").json()
    assert child["status"] == "succeeded" and child["after"]["instance_type"] == "m5.2xlarge"
    parent = client.get(f"{API}/actions/{a['id']}").json()
    assert parent["undone"] and not parent["savings_active"] and not parent["can_undo"]


def test_resize_failure_rolls_back(client):
    conn = demo(client)
    f = by_name(client, conn["id"], "api-backend")   # configured to fail in the demo
    r = client.post(f"{API}/findings/{f['id']}/actions", json={"action": "RESIZE", "options": {}}, headers=H)
    a = client.get(f"{API}/actions/{r.json()['action_id']}").json()
    assert a["status"] == "rolled_back" and "InsufficientInstanceCapacity" in a["error"]
    assert a["after"] == {} and any(s["step"] == "Rollback" and s["status"] == "ok" for s in a["steps_log"])


def test_stop_idle_and_terminate_confirmation(client):
    conn = demo(client)
    f = by_name(client, conn["id"], "dev-sandbox")
    r = client.post(f"{API}/findings/{f['id']}/actions", json={"action": "TERMINATE_INSTANCE"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    r = client.post(f"{API}/findings/{f['id']}/actions", json={"action": "STOP_INSTANCE"}, headers=H)
    assert client.get(f"{API}/actions/{r.json()['action_id']}").json()["status"] == "succeeded"
    # instance is now stopped -> a second stop is blocked by the pre-checks
    again = client.post(f"{API}/findings/{f['id']}/actions", json={"action": "STOP_INSTANCE"}, headers=H)
    assert again.status_code == 422 and again.json()["error"]["code"] == "ACTION_BLOCKED"


def test_needs_review_has_no_action(client):
    conn = demo(client)
    f = by_name(client, conn["id"], "db-replica-1")
    r = client.post(f"{API}/findings/{f['id']}/actions", json={"action": "STOP_INSTANCE"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ACTION_NOT_APPLICABLE"


def test_read_only_connection_cannot_apply(client):
    conn = demo(client)
    client.patch(f"{API}/connections/{conn['id']}", json={"enable_actions": False}, headers=H)
    f = by_name(client, conn["id"], "dev-sandbox")
    r = client.post(f"{API}/findings/{f['id']}/actions", json={"action": "STOP_INSTANCE"}, headers=H)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACTIONS_DISABLED"


def test_dismiss_hides_finding(client):
    conn = demo(client)
    f = by_name(client, conn["id"], "old-poc")
    before = findings(client, conn["id"])["summary"]["potential_monthly_saving"]
    assert client.post(f"{API}/findings/{f['id']}/dismiss", json={"forever": True}, headers=H).status_code == 200
    data = findings(client, conn["id"])
    assert f["id"] not in {x["id"] for x in data["items"]}
    assert data["summary"]["potential_monthly_saving"] < before
    assert f["id"] in {x["id"] for x in findings(client, conn["id"], only_dismissed=True)["items"]}


def test_dashboard_seeded_history(client):
    conn = demo(client)
    s = client.get(f"{API}/dashboard/summary", params={"connection_id": conn["id"], "range": "all"}).json()
    assert s["realized"]["cumulative"] > 0 and s["invested"]["monthly"] > 0
    assert s["timeseries"] and s["top_instances"] and s["actions"]["undone"] == 1
    assert abs(s["timeseries"][-1]["cumulative"] - s["realized"]["cumulative"]) < 0.05


def test_tenancy_isolation(client):
    conn = demo(client)
    f = by_name(client, conn["id"], "dev-sandbox")
    client.cookies.clear()
    register(client, email="bob@example.com", name="Bob")
    assert client.get(f"{API}/connections/{conn['id']}").status_code == 404
    assert client.get(f"{API}/findings/{f['id']}").status_code == 404
    assert client.get(f"{API}/findings", params={"connection_id": conn["id"]}).status_code == 404
    assert client.post(f"{API}/findings/{f['id']}/actions", json={"action": "STOP_INSTANCE"},
                       headers=H).status_code == 404


def test_connection_wizard_and_disconnect(client):
    register(client)
    w = client.post(f"{API}/connections", json={"label": "Prod", "enable_actions": False}, headers=H).json()
    assert len(w["external_id"]) >= 24 and "quickcreate" in w["cloudformation_quick_create_url"]
    assert "sts:ExternalId" in str(w["manual_trust_policy_json"])
    bad = client.post(f"{API}/connections/{w['id']}/verify", json={"role_arn": "nope"}, headers=H)
    assert bad.status_code == 422
    ok = client.post(f"{API}/connections/{w['id']}/verify",
                     json={"role_arn": "arn:aws:iam::111122223333:role/EC2OptimizerAccessRole"}, headers=H).json()
    assert ok["status"] == "connected"
    assert client.delete(f"{API}/connections/{w['id']}", headers=H).status_code == 204
    assert client.get(f"{API}/connections").json() == []
