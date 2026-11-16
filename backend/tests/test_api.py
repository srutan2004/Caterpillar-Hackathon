from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from terrapilot.core.config import ConfigBundle, flatten_keys
from terrapilot.core.security import hash_pin
from terrapilot.core.timeutil import utcnow


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    url = f"sqlite:///{(tmp_path / 'api.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from terrapilot.core.settings import get_settings
    from terrapilot.db.engine import get_engine
    from terrapilot.db.schema import certifications, machines, metadata, sites, users

    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine(url)
    metadata.create_all(engine)
    now = utcnow()
    with engine.begin() as conn:
        conn.execute(
            sites.insert().values(
                id="site_metro",
                name="Metro",
                type="urban_excavation",
                climate_zone="humid_subtropical",
                tz="Asia/Kolkata",
            )
        )
        conn.execute(
            users.insert(),
            [
                {
                    "id": "op_017",
                    "name": "Test Operator",
                    "role": "operator",
                    "locale": "en",
                    "pin_hash": hash_pin("1234", 1000),
                    "badge_id": "B1",
                    "site_id": "site_metro",
                },
                {
                    "id": "sup_metro",
                    "name": "Test Supervisor",
                    "role": "supervisor",
                    "locale": "en",
                    "pin_hash": hash_pin("4321", 1000),
                    "badge_id": "B2",
                    "site_id": "site_metro",
                },
            ],
        )
        conn.execute(
            machines.insert(),
            [
                {
                    "id": "EX-03",
                    "site_id": "site_metro",
                    "manifest_id": "excavator_20t",
                    "machine_class": "excavator",
                    "serial": "s",
                    "qr_token": "tp1.EX-03.x",
                    "hour_meter": 4000.0,
                    "powertrain": "diesel",
                    "status": "available",
                },
                {
                    "id": "EXE-01",
                    "site_id": "site_metro",
                    "manifest_id": "excavator_20t_electric",
                    "machine_class": "excavator",
                    "serial": "s2",
                    "qr_token": "tp1.EXE-01.y",
                    "hour_meter": 900.0,
                    "powertrain": "electric",
                    "status": "available",
                },
            ],
        )
        conn.execute(
            certifications.insert(),
            [
                {
                    "id": "c1",
                    "user_id": "op_017",
                    "module_id": "safety_basics",
                    "issued_at": now - timedelta(days=30),
                    "expires_at": now + timedelta(days=300),
                    "status": "valid",
                },
                {
                    "id": "c2",
                    "user_id": "op_017",
                    "module_id": "excavator_controls",
                    "issued_at": now - timedelta(days=30),
                    "expires_at": now + timedelta(days=300),
                    "status": "valid",
                },
                {
                    "id": "c3",
                    "user_id": "op_017",
                    "module_id": "trenching_101",
                    "issued_at": now - timedelta(days=360),
                    "expires_at": now + timedelta(days=5),
                    "status": "valid",
                },
            ],
        )
    from terrapilot.api.main import create_app

    with TestClient(create_app()) as c:
        yield c
    get_engine.cache_clear()
    get_settings.cache_clear()


def login(client: TestClient, user: str = "op_017", pin: str = "1234") -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": user, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_anonymous_bootstrap_only_has_login(client: TestClient, cfg: ConfigBundle) -> None:
    b = client.get("/api/bootstrap").json()
    assert [n["id"] for n in b["nav"]] == ["login"]
    assert b["ui"]["default_screen"] == "login"
    assert b["product"]["name"] == cfg.app.product.name
    assert b["theme"]["variants"]["dark"]["alert"]["warning"]["bg"].startswith("#")
    assert "form" in b["i18n"] and b["user"] is None


def test_login_layout_is_public_and_form_is_config(client: TestClient, cfg: ConfigBundle) -> None:
    lay = client.get("/api/ui/layout", params={"screen": "login", "device": "cab"}).json()
    assert [w["type"] for w in lay["widgets"]] == ["AppBrand", "FormView"]
    form = client.get("/api/ui/forms/login").json()
    keys = set(flatten_keys(cfg.i18n["en"]))
    assert form["schema"]["properties"]["pin"]["title"] in keys


def test_login_rejects_bad_pin_with_i18n_key(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "op_017", "pin": "0000"})
    assert r.status_code == 401 and r.json()["detail"]["message_key"] == "error.unauthorized"


def test_operator_flow(client: TestClient) -> None:
    h = login(client)
    b = client.get("/api/bootstrap", headers=h).json()
    assert b["user"]["role"] == "operator" and b["ui"]["default_screen"] == "machine_select"
    assert "fleet" not in [n["id"] for n in b["nav"]]
    ms = client.get("/api/machines", headers=h).json()
    assert {m["id"] for m in ms} == {"EX-03", "EXE-01"}
    sel = client.post("/api/auth/machine-select", headers=h, json={"machine_id": "EX-03"}).json()
    assert sel["gating"]["status"] == "full"
    assert {m["module_id"]: m["status"] for m in sel["gating"]["modules"]}["trenching_101"] == "expiring"
    sel_e = client.post("/api/auth/machine-select", headers=h, json={"qr_token": "tp1.EXE-01.y"}).json()
    assert sel_e["gating"]["status"] == "blocked"  # electric_machine_safety missing
    lay = client.get(
        "/api/ui/layout", headers=h, params={"screen": "cockpit", "device": "cab", "manifest_id": "excavator_20t"}
    ).json()
    by_id = {w["id"]: w for w in lay["widgets"]}
    assert by_id["stability"]["resolved"]["bands"]["caution"] == 1.5
    assert by_id["hyd_p"]["resolved"]["sensor"]["bands"]["warning"] == [345, 380]
    assert by_id["alerts"]["resolved"]["max_visible"] == 4


def test_role_gates(client: TestClient) -> None:
    assert client.get("/api/ui/layout", params={"screen": "cockpit", "device": "cab"}).status_code == 401
    h = login(client)
    assert client.get("/api/ui/layout", headers=h, params={"screen": "fleet", "device": "desk"}).status_code == 403
    assert client.get("/api/admin/llm/status", headers=h).status_code == 403
    hs = login(client, "sup_metro", "4321")
    status = client.get("/api/admin/llm/status", headers=hs).json()
    assert "rate_limits" in status and status["profile"] in ("online", "offline")


def test_openapi_publishes_ws_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for name in ("StateDiffMessage", "AlertMessage", "AdvisoryMessage", "MaintenanceAlertMessage", "WsEnvelope"):
        assert name in spec["components"]["schemas"]


def test_ws_requires_token_and_sends_hello(client: TestClient) -> None:
    h = login(client)
    token = h["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/machines/EX-03?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "notice" and msg["code"] == "connected"
