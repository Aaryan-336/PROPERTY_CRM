"""Meta Ads: OAuth, encrypted per-user tokens, reads, confirmed writes, audit.

Meta itself is replaced by an httpx.MockTransport that plays both the Graph
Marketing API and the hosted Ads MCP server.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

from app import meta_ads
from app.config import settings

KEY = Fernet.generate_key().decode()
CID = "120210000000000001"
OTHER_CID = "120210000000000999"


class FakeMeta:
    def __init__(self) -> None:
        self.valid_tokens = {"LONG-TOKEN"}
        self.campaigns = {
            CID: {"id": CID, "name": "Powai 2BHK leads", "status": "ACTIVE",
                  "effective_status": "ACTIVE", "objective": "OUTCOME_LEADS",
                  "daily_budget": "150000", "account_id": "111"},
            OTHER_CID: {"id": OTHER_CID, "name": "Someone else's", "status": "ACTIVE",
                        "effective_status": "ACTIVE", "daily_budget": "50000",
                        "account_id": "999"},
        }
        self.graph_posts: list[tuple[str, dict]] = []
        self.mcp_calls: list[dict] = []
        self.mcp_tools: list[dict] | None = None  # None -> MCP answers 404
        self.revoked = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "mcp.facebook.com":
            return self._mcp(request)
        path = request.url.path.split("/", 2)[-1]
        params = dict(request.url.params)
        if request.method == "POST":
            params.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        if path == "oauth/access_token":
            if "code" in params:
                return httpx.Response(200, json={"access_token": "SHORT"})
            return httpx.Response(200, json={"access_token": "LONG-TOKEN", "expires_in": 5184000})
        if params.get("access_token") not in self.valid_tokens:
            return httpx.Response(400, json={"error": {"code": 190, "message": "Session expired"}})
        assert params.get("appsecret_proof")
        if path == "me":
            return httpx.Response(200, json={"id": "9001", "name": "Dad"})
        if path == "me/permissions":
            if request.method == "DELETE":
                self.revoked = True
                return httpx.Response(200, json={"success": True})
            return httpx.Response(200, json={"data": [
                {"permission": p, "status": "granted"}
                for p in ("ads_mcp_management", "ads_read", "ads_management")]})
        if path == "me/adaccounts":
            return httpx.Response(200, json={"data": [
                {"id": "act_111", "name": "Balaji Ads", "currency": "INR", "account_status": 1}]})
        if path == "act_111/campaigns":
            return httpx.Response(200, json={"data": [self.campaigns[CID]]})
        if path == "act_111/insights":
            return httpx.Response(200, json={"data": [{
                "campaign_id": CID, "campaign_name": "Powai 2BHK leads", "spend": "1234.50",
                "impressions": "10000", "reach": "8000", "clicks": "250", "ctr": "2.5",
                "cpc": "4.94", "cpm": "123.45",
                "actions": [{"action_type": "lead", "value": "12"}]}]})
        if path in self.campaigns:
            if request.method == "POST":
                self.graph_posts.append((path, params))
                for k in ("status", "daily_budget"):
                    if k in params:
                        self.campaigns[path][k] = params[k]
                        if k == "status":
                            self.campaigns[path]["effective_status"] = params[k]
                return httpx.Response(200, json={"success": True})
            return httpx.Response(200, json=self.campaigns[path])
        return httpx.Response(400, json={"error": {"code": 100, "message": f"Unknown path {path}"}})

    def _mcp(self, request: httpx.Request) -> httpx.Response:
        if self.mcp_tools is None:
            return httpx.Response(404)
        if request.headers.get("authorization") != "Bearer LONG-TOKEN":
            return httpx.Response(401)
        msg = json.loads(request.content)
        if "id" not in msg:
            return httpx.Response(202)
        method = msg["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            result = {"tools": self.mcp_tools}
        elif method == "tools/call":
            self.mcp_calls.append(msg["params"])
            name, args = msg["params"]["name"], msg["params"]["arguments"]
            if name == "ads_get_campaigns":
                result = {"content": [{"type": "text", "text": json.dumps(
                    {"data": [self.campaigns[CID]]})}]}
            elif name == "ads_update_campaign":
                c = self.campaigns[args["campaign_id"]]
                if "status" in args:
                    c["status"] = c["effective_status"] = args["status"]
                if "daily_budget" in args:
                    c["daily_budget"] = str(args["daily_budget"])
                result = {"content": [{"type": "text", "text": "{\"success\": true}"}]}
            else:
                result = {"isError": True, "content": [{"type": "text", "text": "nope"}]}
        else:
            return httpx.Response(400)
        body = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        # Answer as SSE, the harder of the two streamable-HTTP shapes.
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "mcp-session-id": "s1"},
            text=f"event: message\ndata: {json.dumps(body)}\n\n",
        )


@pytest.fixture
def meta(monkeypatch, seeded):
    fake = FakeMeta()
    monkeypatch.setattr(settings, "meta_app_id", "app-1")
    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    monkeypatch.setattr(settings, "meta_redirect_uri", "https://api.test/meta-ads/oauth/callback")
    monkeypatch.setattr(settings, "meta_token_encryption_key", KEY)
    monkeypatch.setattr(settings, "meta_post_connect_redirect", "https://crm.test/meta-ads")
    monkeypatch.setattr(settings, "meta_ads_transport", "auto")
    monkeypatch.setattr(settings, "meta_mcp_tools", "")
    monkeypatch.setattr(meta_ads, "_TRANSPORT", httpx.MockTransport(fake))
    meta_ads.reset_mcp_cache()

    from sqlalchemy import delete

    from app.db import SessionLocal, system_scope
    from app.models import MetaAdConnection

    db = SessionLocal()
    with system_scope():
        db.execute(delete(MetaAdConnection))
        db.commit()
    db.close()
    yield fake
    meta_ads.reset_mcp_cache()


def _connect(client, headers) -> httpx.Response:
    start = client.post("/meta-ads/oauth/start", headers=headers)
    assert start.status_code == 200, start.text
    url = urlparse(start.json()["authorize_url"])
    q = parse_qs(url.query)
    assert q["client_id"] == ["app-1"]
    assert "ads_mcp_management" in q["scope"][0]
    return client.get(
        "/meta-ads/oauth/callback",
        params={"code": "abc", "state": q["state"][0]},
        follow_redirects=False,
    )


def _row(user_id):
    from sqlalchemy import select

    from app.db import SessionLocal, system_scope
    from app.models import MetaAdConnection

    db = SessionLocal()
    with system_scope():
        row = db.execute(
            select(MetaAdConnection).where(MetaAdConnection.user_id == user_id)
        ).scalar_one_or_none()
    db.close()
    return row


def _audit(action=None, resource_type="meta_ads"):
    from sqlalchemy import select

    from app.db import SessionLocal, system_scope
    from app.models import AuditLog

    db = SessionLocal()
    with system_scope():
        stmt = select(AuditLog).where(AuditLog.resource_type == resource_type)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        rows = db.execute(stmt.order_by(AuditLog.id.desc())).scalars().all()
    db.close()
    return rows


def test_unconfigured_server_reports_it_and_refuses_to_connect(client, owner_h, seeded, monkeypatch):
    monkeypatch.setattr(settings, "meta_token_encryption_key", "")
    body = client.get("/meta-ads/status", headers=owner_h).json()
    assert body["configured"] is False and body["state"] == "disconnected"
    assert client.post("/meta-ads/oauth/start", headers=owner_h).status_code == 503


def test_connect_stores_an_encrypted_token_and_never_returns_it(client, owner_h, seeded, meta):
    res = _connect(client, owner_h)
    assert res.status_code == 303
    assert res.headers["location"] == "https://crm.test/meta-ads?meta=connected"

    row = _row(seeded["owner_id"])
    assert row.status == "connected"
    assert "LONG-TOKEN" not in row.access_token_enc
    assert Fernet(KEY.encode()).decrypt(row.access_token_enc.encode()) == b"LONG-TOKEN"
    assert row.oauth_state_hash is None
    assert row.ad_account_id == "act_111"

    status = client.get("/meta-ads/status", headers=owner_h)
    assert status.json()["state"] == "connected"
    assert status.json()["ad_account_name"] == "Balaji Ads"
    assert status.json()["missing_scopes"] == []
    assert "LONG-TOKEN" not in status.text

    assert _audit("connect")[0].user_id == seeded["owner_id"]


def test_a_state_is_single_use_and_unknown_states_are_refused(client, owner_h, meta):
    start = client.post("/meta-ads/oauth/start", headers=owner_h).json()
    state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
    first = client.get("/meta-ads/oauth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert first.headers["location"].endswith("meta=connected")
    replay = client.get("/meta-ads/oauth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert replay.headers["location"].endswith("meta=error")
    forged = client.get("/meta-ads/oauth/callback", params={"code": "c", "state": "made-up"}, follow_redirects=False)
    assert forged.headers["location"].endswith("meta=error")


def test_denying_on_meta_leaves_the_user_disconnected(client, owner_h, seeded, meta):
    start = client.post("/meta-ads/oauth/start", headers=owner_h).json()
    state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
    res = client.get("/meta-ads/oauth/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert res.headers["location"].endswith("meta=cancelled")
    assert client.get("/meta-ads/status", headers=owner_h).json()["state"] == "disconnected"


def test_roles_without_the_capability_are_refused(client, alice_h, carol_h, meta):
    for h in (alice_h, carol_h):
        assert client.get("/meta-ads/status", headers=h).status_code == 403
        assert client.post("/meta-ads/oauth/start", headers=h).status_code == 403
        assert client.get("/meta-ads/campaigns", headers=h).status_code == 403


def test_one_users_connection_is_invisible_to_another(client, owner_h, seeded, meta):
    """Two owners: the second sees 'disconnected', never the first's account."""
    from app.db import SessionLocal, system_scope
    from app.models import User
    from app.security import hash_password

    db = SessionLocal()
    with system_scope():
        from sqlalchemy import select

        second = db.execute(select(User).where(User.email == "o2@t.local")).scalar_one_or_none()
        if second is None:
            db.add(User(name="Owner Two", email="o2@t.local", role="owner",
                        password_hash=hash_password("pw12345678")))
            db.commit()
    db.close()
    token = client.post("/auth/login", json={"email": "o2@t.local", "password": "pw12345678"}).json()["access_token"]
    other_h = {"authorization": f"Bearer {token}"}

    _connect(client, owner_h)
    body = client.get("/meta-ads/status", headers=other_h).json()
    assert body["state"] == "disconnected" and body["ad_account_id"] is None
    assert client.get("/meta-ads/campaigns", headers=other_h).json()["error"]["code"] == "meta_not_connected"
    assert client.post(f"/meta-ads/campaigns/{CID}/status", headers=other_h,
                       json={"status": "PAUSED", "confirm": True}).status_code == 409


def test_campaigns_and_insights_load_via_graph_when_mcp_has_no_tool(client, owner_h, meta):
    _connect(client, owner_h)
    body = client.get("/meta-ads/campaigns", headers=owner_h).json()
    assert body["via"] == "graph"
    assert body["currency"] == "INR"
    assert body["campaigns"][0]["name"] == "Powai 2BHK leads"
    assert body["campaigns"][0]["daily_budget"] == "1500.00"

    ins = client.get("/meta-ads/insights?date_preset=last_30d", headers=owner_h).json()
    assert ins["totals"]["spend"] == 1234.5
    assert ins["totals"]["leads"] == 12
    assert ins["rows"][0]["clicks"] == 250
    assert client.get("/meta-ads/insights?date_preset=forever", headers=owner_h).status_code == 400


def test_writes_require_confirmation(client, owner_h, meta):
    _connect(client, owner_h)
    res = client.post(f"/meta-ads/campaigns/{CID}/status", headers=owner_h,
                      json={"status": "PAUSED", "confirm": False})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "confirmation_required"
    assert meta.graph_posts == []


def test_pause_and_resume_are_applied_and_audited(client, owner_h, seeded, meta):
    _connect(client, owner_h)
    res = client.post(f"/meta-ads/campaigns/{CID}/status", headers=owner_h,
                      json={"status": "PAUSED", "confirm": True})
    assert res.status_code == 200, res.text
    assert res.json()["campaign"]["status"] == "PAUSED"
    assert meta.graph_posts[-1] == (CID, meta.graph_posts[-1][1])
    assert meta.graph_posts[-1][1]["status"] == "PAUSED"

    entry = _audit("edit")[0]
    assert entry.user_id == seeded["owner_id"]
    assert entry.detail["meta_action"] == "pause"
    assert entry.detail["changed_fields"]["status"] == {"from": "ACTIVE", "to": "PAUSED"}
    assert "LONG-TOKEN" not in json.dumps(entry.detail)

    res = client.post(f"/meta-ads/campaigns/{CID}/status", headers=owner_h,
                      json={"status": "ACTIVE", "confirm": True})
    assert res.json()["campaign"]["status"] == "ACTIVE"
    assert _audit("edit")[0].detail["meta_action"] == "resume"


def test_daily_budget_is_converted_to_minor_units_and_audited(client, owner_h, meta):
    _connect(client, owner_h)
    res = client.post(f"/meta-ads/campaigns/{CID}/budget", headers=owner_h,
                      json={"daily_budget": "2000.50", "confirm": True})
    assert res.status_code == 200, res.text
    assert meta.graph_posts[-1][1]["daily_budget"] == "200050"
    assert res.json()["campaign"]["daily_budget"] == "2000.50"
    detail = _audit("edit")[0].detail
    assert detail["changed_fields"]["daily_budget"] == {"from": "1500.00", "to": "2000.50"}


def test_a_campaign_outside_the_connected_account_cannot_be_touched(client, owner_h, meta):
    _connect(client, owner_h)
    res = client.post(f"/meta-ads/campaigns/{OTHER_CID}/status", headers=owner_h,
                      json={"status": "PAUSED", "confirm": True})
    assert res.status_code == 404
    assert client.post("/meta-ads/campaigns/../me/status", headers=owner_h,
                       json={"status": "PAUSED", "confirm": True}).status_code in (404, 405)
    assert meta.graph_posts == []


def test_a_revoked_token_flips_the_connection_to_reconnect_required(client, owner_h, meta):
    _connect(client, owner_h)
    meta.valid_tokens.clear()
    res = client.get("/meta-ads/campaigns", headers=owner_h)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "meta_reauth_required"
    assert client.get("/meta-ads/status", headers=owner_h).json()["state"] == "reauth_required"

    meta.valid_tokens.add("LONG-TOKEN")
    _connect(client, owner_h)
    assert client.get("/meta-ads/status", headers=owner_h).json()["state"] == "connected"


def test_an_expired_token_reads_as_reconnect_required(client, owner_h, seeded, meta):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import MetaAdConnection

    _connect(client, owner_h)
    db = SessionLocal()
    db.execute(update(MetaAdConnection).values(
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    db.commit()
    db.close()
    assert client.get("/meta-ads/status", headers=owner_h).json()["state"] == "reauth_required"


def test_disconnect_wipes_the_token_and_revokes_at_meta(client, owner_h, seeded, meta):
    _connect(client, owner_h)
    res = client.post("/meta-ads/disconnect", headers=owner_h)
    assert res.status_code == 200
    row = _row(seeded["owner_id"])
    assert row.access_token_enc is None and row.status == "disconnected"
    assert meta.revoked
    assert _audit("disconnect")


def test_mcp_tools_are_used_when_the_server_offers_them(client, owner_h, meta):
    meta.mcp_tools = [
        {"name": "ads_get_campaigns", "inputSchema": {
            "type": "object", "properties": {"ad_account_id": {"type": "string"}},
            "required": ["ad_account_id"]}},
        {"name": "ads_update_campaign", "inputSchema": {
            "type": "object", "properties": {
                "campaign_id": {"type": "string"}, "status": {"type": "string"},
                "daily_budget": {"type": "integer"}},
            "required": ["campaign_id"]}},
        {"name": "ads_create_campaign", "inputSchema": {"type": "object", "properties": {}}},
    ]
    _connect(client, owner_h)
    body = client.get("/meta-ads/campaigns", headers=owner_h).json()
    assert body["via"] == "mcp"
    assert meta.mcp_calls[-1] == {"name": "ads_get_campaigns", "arguments": {"ad_account_id": "act_111"}}

    res = client.post(f"/meta-ads/campaigns/{CID}/status", headers=owner_h,
                      json={"status": "PAUSED", "confirm": True})
    assert res.json()["via"] == "mcp"
    assert res.json()["campaign"]["status"] == "PAUSED"
    assert meta.mcp_calls[-1]["arguments"] == {"campaign_id": CID, "status": "PAUSED"}
    assert meta.graph_posts == []
    assert _audit("edit")[0].detail["via"] == "mcp"


def test_argument_mapping_refuses_to_guess():
    tool = {"name": "t", "inputSchema": {"properties": {"x": {}}, "required": ["x"]}}
    with pytest.raises(meta_ads._McpUnusable):
        meta_ads.build_arguments(tool, {"campaign_id": "1"})
