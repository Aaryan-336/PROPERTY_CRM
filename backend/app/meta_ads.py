"""Meta Ads: OAuth, and campaign reads/writes on behalf of one CRM user.

Two upstreams, one user token:

* Meta's hosted Ads MCP server (``settings.meta_ads_mcp_url``). The backend is
  the MCP client -- JSON-RPC over streamable HTTP, the user's token as Bearer.
  The server's tool catalogue is discovered with ``tools/list`` rather than
  hard-coded, because it is in beta and its names are Meta's to change;
  ``META_MCP_TOOLS`` pins names if discovery ever guesses wrong.
* The Graph Marketing API, which accepts the same token and scopes. It is the
  fallback when no MCP tool fits an operation, and it is always used for the
  pre-write ownership check, so a write can only ever touch a campaign inside
  the ad account this user connected.

Nothing in this module returns a token to a caller outside it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings

log = logging.getLogger("balaji.meta_ads")

OAUTH_STATE_TTL = timedelta(minutes=10)
HTTP_TIMEOUT = 25.0
MCP_PROTOCOL_VERSION = "2025-06-18"
TOOLS_CACHE_SECONDS = 600

DATE_PRESETS = (
    "today",
    "yesterday",
    "last_7d",
    "last_14d",
    "last_30d",
    "this_month",
    "last_month",
    "maximum",
)

# Meta stores budgets in the currency's minor unit, except for these, whose
# offset is 1 (Marketing API "Currencies" reference).
ZERO_DECIMAL_CURRENCIES = frozenset(
    {"CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"}
)

# Test seam: tests install an httpx.MockTransport here.
_TRANSPORT: httpx.BaseTransport | None = None


class MetaAuthError(Exception):
    """Meta rejected the token. The connection needs a fresh authorization."""


class MetaApiError(Exception):
    """Any other upstream failure, with a message fit to show the user."""


class _McpUnusable(Exception):
    """This operation cannot be done over MCP; auto mode falls back to Graph."""


def _client() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT, transport=_TRANSPORT)


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.meta_graph_version}"


def minor_unit_factor(currency: str | None) -> int:
    return 1 if (currency or "").upper() in ZERO_DECIMAL_CURRENCIES else 100


def to_minor(amount: Decimal, currency: str | None) -> int:
    return int((amount * minor_unit_factor(currency)).to_integral_value())


def to_major(minor: int | None, currency: str | None) -> Decimal | None:
    if minor is None:
        return None
    factor = minor_unit_factor(currency)
    return (Decimal(minor) / factor).quantize(Decimal("1") if factor == 1 else Decimal("0.01"))


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


def new_oauth_state() -> tuple[str, str, datetime]:
    """(state for the URL, hash to store, expiry)."""
    state = secrets.token_urlsafe(32)
    return state, hash_state(state), datetime.now(timezone.utc) + OAUTH_STATE_TTL


def hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": settings.meta_scopes,
    }
    return (
        f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?"
        + urlencode(params)
    )


def _appsecret_proof(token: str) -> str:
    return hmac.new(
        settings.meta_app_secret.encode(), token.encode(), hashlib.sha256
    ).hexdigest()


def _raise_for_graph(res: httpx.Response) -> dict:
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code < 400 and not (isinstance(body, dict) and "error" in body):
        return body
    err = body.get("error", {}) if isinstance(body, dict) else {}
    code = err.get("code")
    message = err.get("error_user_msg") or err.get("message") or f"HTTP {res.status_code}"
    # 190: token expired/invalidated; 102: session key invalid; 463/467 subcodes
    # ride on 190. All mean the same thing to us: authorize again.
    if code in (102, 190) or res.status_code == 401:
        raise MetaAuthError(message)
    raise MetaApiError(message)


def exchange_code(code: str) -> tuple[str, datetime | None]:
    """Authorization code -> long-lived user token (about 60 days)."""
    with _client() as http:
        short = _raise_for_graph(
            http.get(
                f"{_graph_base()}/oauth/access_token",
                params={
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "redirect_uri": settings.meta_redirect_uri,
                    "code": code,
                },
            )
        )
        long = _raise_for_graph(
            http.get(
                f"{_graph_base()}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "fb_exchange_token": short["access_token"],
                },
            )
        )
    expires_in = long.get("expires_in")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )
    return long["access_token"], expires_at


# ---------------------------------------------------------------------------
# Graph Marketing API
# ---------------------------------------------------------------------------

CAMPAIGN_FIELDS = (
    "id,name,status,effective_status,objective,daily_budget,lifetime_budget,"
    "budget_remaining,start_time,stop_time,account_id"
)
INSIGHT_FIELDS = (
    "campaign_id,campaign_name,spend,impressions,reach,clicks,ctr,cpc,cpm,actions"
)
LEAD_ACTION_TYPES = ("lead", "onsite_conversion.lead_grouped", "leadgen_grouped")


class GraphAds:
    def __init__(self, token: str) -> None:
        self._token = token

    def _params(self, extra: dict | None = None) -> dict:
        return {
            "access_token": self._token,
            "appsecret_proof": _appsecret_proof(self._token),
            **(extra or {}),
        }

    def get(self, path: str, params: dict | None = None) -> dict:
        with _client() as http:
            return _raise_for_graph(
                http.get(f"{_graph_base()}/{path}", params=self._params(params))
            )

    def post(self, path: str, data: dict) -> dict:
        with _client() as http:
            return _raise_for_graph(
                http.post(f"{_graph_base()}/{path}", data=self._params(data))
            )

    def delete(self, path: str) -> dict:
        with _client() as http:
            return _raise_for_graph(
                http.delete(f"{_graph_base()}/{path}", params=self._params())
            )

    def me(self) -> dict:
        return self.get("me", {"fields": "id,name"})

    def granted_scopes(self) -> list[str]:
        rows = self.get("me/permissions").get("data", [])
        return sorted(r["permission"] for r in rows if r.get("status") == "granted")

    def ad_accounts(self) -> list[dict]:
        rows = self.get(
            "me/adaccounts",
            {"fields": "id,account_id,name,currency,account_status", "limit": 100},
        ).get("data", [])
        return [
            {
                "id": r["id"],
                "name": r.get("name") or r["id"],
                "currency": r.get("currency"),
                "account_status": r.get("account_status"),
            }
            for r in rows
        ]

    def campaigns(self, account_id: str) -> list[dict]:
        rows = self.get(
            f"{account_id}/campaigns", {"fields": CAMPAIGN_FIELDS, "limit": 100}
        ).get("data", [])
        return [normalize_campaign(r) for r in rows]

    def campaign(self, campaign_id: str) -> dict:
        return normalize_campaign(self.get(campaign_id, {"fields": CAMPAIGN_FIELDS}))

    def insights(self, account_id: str, date_preset: str) -> list[dict]:
        rows = self.get(
            f"{account_id}/insights",
            {
                "level": "campaign",
                "date_preset": date_preset,
                "fields": INSIGHT_FIELDS,
                "limit": 200,
            },
        ).get("data", [])
        return [normalize_insight(r) for r in rows]

    def set_status(self, campaign_id: str, status: str) -> None:
        self.post(campaign_id, {"status": status})

    def set_daily_budget(self, campaign_id: str, minor: int) -> None:
        self.post(campaign_id, {"daily_budget": str(minor)})

    def revoke(self) -> None:
        self.delete("me/permissions")


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(Decimal(str(value)))
    except Exception:
        return None


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_campaign(r: dict) -> dict:
    return {
        "id": str(r.get("id") or r.get("campaign_id") or ""),
        "name": r.get("name") or r.get("campaign_name") or "",
        "status": (r.get("status") or r.get("configured_status") or "").upper(),
        "effective_status": (r.get("effective_status") or r.get("status") or "").upper(),
        "objective": r.get("objective"),
        "daily_budget": _int_or_none(r.get("daily_budget")),
        "lifetime_budget": _int_or_none(r.get("lifetime_budget")),
        "budget_remaining": _int_or_none(r.get("budget_remaining")),
        "start_time": r.get("start_time"),
        "stop_time": r.get("stop_time"),
        "account_id": str(r["account_id"]) if r.get("account_id") else None,
    }


def normalize_insight(r: dict) -> dict:
    actions = {
        a.get("action_type"): _num(a.get("value"))
        for a in (r.get("actions") or [])
        if isinstance(a, dict)
    }
    leads = next((actions[t] for t in LEAD_ACTION_TYPES if t in actions), 0.0)
    if "leads" in r:
        leads = _num(r["leads"])
    return {
        "campaign_id": str(r.get("campaign_id") or r.get("id") or ""),
        "campaign_name": r.get("campaign_name") or r.get("name") or "",
        "spend": _num(r.get("spend")),
        "impressions": int(_num(r.get("impressions"))),
        "reach": int(_num(r.get("reach"))),
        "clicks": int(_num(r.get("clicks"))),
        "ctr": _num(r.get("ctr")),
        "cpc": _num(r.get("cpc")),
        "cpm": _num(r.get("cpm")),
        "leads": int(leads),
    }


# ---------------------------------------------------------------------------
# Hosted Ads MCP
# ---------------------------------------------------------------------------

_tools_cache: dict[str, Any] = {"at": 0.0, "tools": None}

# Our operation -> preferred tool names, then keyword rules for discovery.
_TOOL_PREFERENCES: dict[str, tuple[str, ...]] = {
    "list_campaigns": ("ads_get_campaigns", "ads_list_campaigns", "get_campaigns", "list_campaigns"),
    "insights": ("ads_get_insights", "ads_get_campaign_insights", "get_insights", "get_campaign_insights"),
    "update_campaign": ("ads_update_campaign", "update_campaign", "ads_edit_campaign"),
}
_TOOL_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # (all-of keywords, none-of keywords)
    "list_campaigns": (("campaign",), ("insight", "create", "update", "delete", "edit", "benchmark", "opportunity")),
    "insights": (("insight",), ("benchmark", "industry", "advertiser_context", "opportunity")),
    "update_campaign": (("campaign", "update"), ("create", "delete")),
}
_ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "account_id": ("ad_account_id", "account_id", "act_id", "adaccount_id", "ad_account"),
    "campaign_id": ("campaign_id", "object_id", "id", "campaign"),
    "status": ("status",),
    "daily_budget": ("daily_budget", "daily_budget_amount", "budget"),
    "date_preset": ("date_preset", "time_range_preset", "date_range"),
    "level": ("level",),
}


def reset_mcp_cache() -> None:
    _tools_cache.update(at=0.0, tools=None)


class McpAds:
    def __init__(self, token: str) -> None:
        self._token = token
        self._session_id: str | None = None
        self._next_id = 0

    def _headers(self) -> dict:
        h = {
            "authorization": f"Bearer {self._token}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": MCP_PROTOCOL_VERSION,
        }
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    def _rpc(self, http: httpx.Client, method: str, params: dict | None = None, notify: bool = False) -> Any:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            self._next_id += 1
            payload["id"] = self._next_id
        try:
            res = http.post(settings.meta_ads_mcp_url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise _McpUnusable(f"MCP unreachable: {exc}") from exc
        if res.status_code in (401, 403):
            raise MetaAuthError("Meta Ads MCP rejected the authorization.")
        if notify:
            return None
        if res.status_code >= 400:
            raise _McpUnusable(f"MCP HTTP {res.status_code}")
        sid = res.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        message = _parse_rpc_response(res, payload["id"])
        if "error" in message:
            raise _McpUnusable(f"MCP error: {message['error'].get('message')}")
        return message.get("result")

    def _session(self, http: httpx.Client) -> None:
        self._rpc(
            http,
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "balaji-crm", "version": "1.0"},
            },
        )
        self._rpc(http, "notifications/initialized", notify=True)

    def tools(self) -> list[dict]:
        cached = _tools_cache["tools"]
        if cached is not None and time.monotonic() - _tools_cache["at"] < TOOLS_CACHE_SECONDS:
            return cached
        with _client() as http:
            self._session(http)
            tools: list[dict] = []
            cursor = None
            for _ in range(10):
                result = self._rpc(http, "tools/list", {"cursor": cursor} if cursor else {})
                tools.extend(result.get("tools", []))
                cursor = result.get("nextCursor")
                if not cursor:
                    break
        _tools_cache.update(at=time.monotonic(), tools=tools)
        return tools

    def call(self, operation: str, intent: dict[str, Any]) -> Any:
        tool = resolve_tool(operation, self.tools())
        if tool is None:
            raise _McpUnusable(f"No MCP tool matches {operation!r}")
        arguments = build_arguments(tool, intent)
        with _client() as http:
            self._session(http)
            result = self._rpc(http, "tools/call", {"name": tool["name"], "arguments": arguments})
        if not isinstance(result, dict) or result.get("isError"):
            raise _McpUnusable(f"MCP tool {tool['name']} reported an error: {_result_text(result)[:300]}")
        return _result_payload(result)


def _parse_rpc_response(res: httpx.Response, request_id: int) -> dict:
    ctype = res.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for block in res.text.split("\n\n"):
            data = "\n".join(
                line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")
            )
            if not data:
                continue
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == request_id:
                return msg
        raise _McpUnusable("MCP stream ended without a response")
    try:
        msg = res.json()
    except ValueError as exc:
        raise _McpUnusable("MCP returned non-JSON") from exc
    if isinstance(msg, list):
        msg = next((m for m in msg if m.get("id") == request_id), {})
    return msg


def resolve_tool(operation: str, tools: list[dict]) -> dict | None:
    by_name = {t.get("name"): t for t in tools if t.get("name")}
    pinned = _pinned_tools().get(operation)
    if pinned:
        return by_name.get(pinned)
    for name in _TOOL_PREFERENCES[operation]:
        if name in by_name:
            return by_name[name]
    need, avoid = _TOOL_RULES[operation]
    for name in sorted(by_name):
        lowered = name.lower()
        if all(k in lowered for k in need) and not any(k in lowered for k in avoid):
            return by_name[name]
    return None


def _pinned_tools() -> dict[str, str]:
    if not settings.meta_mcp_tools:
        return {}
    try:
        value = json.loads(settings.meta_mcp_tools)
        return value if isinstance(value, dict) else {}
    except ValueError:
        log.warning("META_MCP_TOOLS is not valid JSON; ignoring it")
        return {}


def build_arguments(tool: dict, intent: dict[str, Any]) -> dict:
    """Map our intent onto the tool's declared input schema, or give up.

    Giving up is deliberate: guessing at an argument the schema does not
    declare is how a write lands on the wrong object.
    """
    schema = tool.get("inputSchema") or {}
    props: dict = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    args: dict[str, Any] = {}
    for key, value in intent.items():
        if value is None:
            continue
        target = next((a for a in _ARG_ALIASES.get(key, (key,)) if a in props and a not in args), None)
        if target is None:
            raise _McpUnusable(f"Tool {tool.get('name')} has no argument for {key}")
        args[target] = value
    missing = required - set(args)
    if missing:
        raise _McpUnusable(f"Tool {tool.get('name')} needs {sorted(missing)}")
    return args


def _result_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)
    return " ".join(
        c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)
    )


def _result_payload(result: dict) -> Any:
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    for c in result.get("content", []):
        if isinstance(c, dict) and c.get("type") == "text":
            try:
                return json.loads(c.get("text", ""))
            except ValueError:
                continue
    raise _McpUnusable("MCP result carried no structured data")


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (payload[k] for k in ("data", "campaigns", "results", "insights", "rows") if isinstance(payload.get(k), list)),
            None,
        )
        if rows is None:
            raise _McpUnusable("MCP result had no row list")
    else:
        raise _McpUnusable("MCP result had no row list")
    return [r for r in rows if isinstance(r, dict)]


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class AdsClient:
    """Campaign operations for one user's token and chosen ad account."""

    def __init__(self, token: str, account_id: str) -> None:
        self.graph = GraphAds(token)
        self.mcp = McpAds(token)
        self.account_id = account_id
        self.mode = settings.meta_ads_transport.lower()

    def _via_mcp(self, operation: str, intent: dict) -> Any:
        if self.mode == "graph":
            raise _McpUnusable("graph pinned")
        try:
            return self.mcp.call(operation, intent)
        except _McpUnusable as exc:
            if self.mode == "mcp":
                raise MetaApiError(f"Meta Ads MCP could not complete this: {exc}") from exc
            log.info("Meta Ads MCP unusable for %s, using Graph: %s", operation, exc)
            raise

    def campaigns(self) -> tuple[list[dict], str]:
        try:
            rows = [normalize_campaign(r) for r in _rows(self._via_mcp("list_campaigns", {"account_id": self.account_id}))]
            if rows and all(r["id"] for r in rows):
                return rows, "mcp"
            if rows:
                raise _McpUnusable("rows without ids")
        except _McpUnusable:
            pass
        return self.graph.campaigns(self.account_id), "graph"

    def insights(self, date_preset: str) -> tuple[list[dict], str]:
        try:
            payload = self._via_mcp(
                "insights",
                {"account_id": self.account_id, "date_preset": date_preset, "level": "campaign"},
            )
            rows = [normalize_insight(r) for r in _rows(payload)]
            if all(r["campaign_id"] for r in rows):
                return rows, "mcp"
        except _McpUnusable:
            pass
        return self.graph.insights(self.account_id, date_preset), "graph"

    def set_status(self, campaign_id: str, status: str) -> str:
        try:
            self._via_mcp("update_campaign", {"campaign_id": campaign_id, "status": status})
            return "mcp"
        except _McpUnusable:
            pass
        self.graph.set_status(campaign_id, status)
        return "graph"

    def set_daily_budget(self, campaign_id: str, minor: int) -> str:
        try:
            self._via_mcp("update_campaign", {"campaign_id": campaign_id, "daily_budget": minor})
            return "mcp"
        except _McpUnusable:
            pass
        self.graph.set_daily_budget(campaign_id, minor)
        return "graph"
