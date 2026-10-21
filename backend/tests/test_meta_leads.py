"""Meta Lead Ads intake, lead performance, and reel-based campaign creation.

Reuses the FakeMeta from test_meta_ads and teaches it Pages, lead forms, leads,
Instagram media and campaign creation.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from app import meta_leads, meta_reels
from app.config import settings
from tests.test_meta_ads import FakeMeta, _audit, _connect, meta  # noqa: F401

PAGE = "777"
IG = "ig1"
FORM = "555"
LEAD = {
    "id": "L1",
    "created_time": "2026-10-20T10:00:00+0000",
    "form_id": FORM,
    "campaign_id": "120210000000000001",
    "campaign_name": "Powai 2BHK leads",
    "ad_id": "9001",
    "ad_name": "Reel ad",
    "platform": "ig",
    "field_data": [
        {"name": "full_name", "values": ["Rohan Mehta"]},
        {"name": "phone_number", "values": ["p:+919820011223"]},
        {"name": "email", "values": ["rohan@example.com"]},
        {"name": "what_configuration_are_you_looking_for?", "values": ["3 BHK"]},
        {"name": "preferred_location", "values": ["Malad West, Goregaon"]},
    ],
}
REELS = [
    {"id": "9101", "caption": "Tour of a 3BHK in Malad West", "media_product_type": "REELS",
     "media_type": "VIDEO", "permalink": "https://instagram.com/reel/a", "timestamp": "2026-10-01T10:00:00+0000"},
    {"id": "9102", "caption": "Weekend vibes", "media_product_type": "REELS",
     "media_type": "VIDEO", "permalink": "https://instagram.com/reel/b", "timestamp": "2026-10-02T10:00:00+0000"},
    {"id": "9103", "caption": "Brand new reel", "media_product_type": "REELS",
     "media_type": "VIDEO", "permalink": "https://instagram.com/reel/c", "timestamp": "2026-10-19T10:00:00+0000"},
]
INSIGHTS = {
    "9101": {"reach": 20000, "views": 40000, "likes": 900, "comments": 60, "shares": 300, "saved": 250},
    "9102": {"reach": 18000, "views": 25000, "likes": 200, "comments": 5, "shares": 3, "saved": 4},
    "9103": {"reach": 50, "views": 80, "likes": 3, "comments": 0, "shares": 0, "saved": 0},
}


class FakeMetaLeads(FakeMeta):
    def __init__(self) -> None:
        super().__init__()
        self.valid_tokens.add("PAGE-TOKEN")
        self.leads = {"L1": dict(LEAD)}
        self.subscribed: list[str] = []
        self.created: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.fail_creative = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        path = request.url.path.split("/", 2)[-1]
        params = dict(request.url.params)
        if request.method == "POST":
            params.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        known = path == "me/accounts" or path.split("/")[0] in {PAGE, FORM, IG, "search", *self.leads} or \
            path.startswith(("act_111/campaigns", "act_111/adsets", "act_111/adcreatives", "act_111/ads", "91", "c-", "adset-"))
        if not known and not (request.method == "DELETE" and path.startswith("c-")):
            return super().__call__(request)
        if params.get("access_token") not in self.valid_tokens:
            return httpx.Response(400, json={"error": {"code": 190, "message": "Session expired"}})
        if path == "me/accounts":
            return httpx.Response(200, json={"data": [{
                "id": PAGE, "name": "Balaji Realty", "access_token": "PAGE-TOKEN",
                "instagram_business_account": {"id": IG, "username": "balaji.realty"}}]})
        if path == f"{PAGE}/subscribed_apps":
            assert params["access_token"] == "PAGE-TOKEN"
            self.subscribed.append(params["subscribed_fields"])
            return httpx.Response(200, json={"success": True})
        if path == f"{PAGE}/leadgen_forms":
            return httpx.Response(200, json={"data": [{"id": FORM, "name": "Enquiry", "status": "ACTIVE"}]})
        if path == f"{FORM}/leads":
            return httpx.Response(200, json={"data": list(self.leads.values())})
        if path in self.leads:
            return httpx.Response(200, json=self.leads[path])
        if path == f"{IG}/media":
            return httpx.Response(200, json={"data": REELS})
        if path.endswith("/insights") and path.split("/")[0] in INSIGHTS:
            return httpx.Response(200, json={"data": [
                {"name": k, "values": [{"value": v}]} for k, v in INSIGHTS[path.split("/")[0]].items()]})
        if path == "search":
            return httpx.Response(200, json={"data": [{"key": "2418956", "name": "Mumbai"}]})
        if request.method == "DELETE":
            self.deleted.append(path)
            return httpx.Response(200, json={"success": True})
        if request.method == "POST" and path.startswith("act_111/"):
            kind = path.split("/")[1]
            if kind == "adcreatives" and self.fail_creative:
                return httpx.Response(400, json={"error": {"code": 100, "message": "Creative rejected"}})
            self.created.append((kind, params))
            return httpx.Response(200, json={"id": {"campaigns": "c-1", "adsets": "adset-1",
                                                    "adcreatives": "cr-1", "ads": "ad-1"}[kind]})
        return super().__call__(request)


@pytest.fixture
def fm(monkeypatch, meta):  # noqa: F811
    fake = FakeMetaLeads()
    monkeypatch.setattr(settings, "meta_webhook_verify_token", "verify-me")
    from app import meta_ads
    monkeypatch.setattr(meta_ads, "_TRANSPORT", httpx.MockTransport(fake))
    from sqlalchemy import delete, select, update
    from app.db import SessionLocal, system_scope
    from app.models import Activity, Contact, MetaLead

    db = SessionLocal()
    with system_scope():
        db.execute(update(MetaLead).values(contact_id=None))
        db.execute(delete(MetaLead))
        ids = select(Contact.id).where(Contact.lead_source == "Meta Ads")
        db.execute(delete(Activity).where(Activity.contact_id.in_(ids)))
        db.execute(delete(Contact).where(Contact.lead_source == "Meta Ads"))
        db.commit()
    db.close()
    return fake


def _sign(body: bytes, secret: str = "app-secret") -> dict:
    return {"x-hub-signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


def _event(leadgen_id: str = "L1") -> bytes:
    return json.dumps({"object": "page", "entry": [{"id": PAGE, "changes": [{
        "field": "leadgen", "value": {"leadgen_id": leadgen_id, "page_id": PAGE, "form_id": FORM}}]}]}).encode()


def _contacts(source="Meta Ads"):
    from sqlalchemy import select
    from app.db import SessionLocal, system_scope
    from app.models import Contact

    db = SessionLocal()
    with system_scope():
        rows = db.execute(select(Contact).where(Contact.lead_source == source)).scalars().all()
    db.close()
    return rows


# --------------------------------------------------------------- pure mapping


def test_form_answers_map_onto_a_contact_and_keep_everything_else():
    f = meta_leads.map_contact_fields(LEAD["field_data"])
    assert (f["first_name"], f["last_name"]) == ("Rohan", "Mehta")
    assert f["phone"] == "+919820011223"          # Meta's "p:" prefix removed
    assert f["bhk"] == 3
    assert f["preferred_locations"] == ["Malad West", "Goregaon"]
    assert "what_configuration_are_you_looking_for?" in f["answers"]


def test_a_form_with_no_name_still_becomes_a_contact():
    f = meta_leads.map_contact_fields([{"name": "phone_number", "values": ["9820011223"]}])
    assert f["first_name"] == "Meta lead" and f["phone"] == "9820011223"


# -------------------------------------------------------------- connect + page


def test_connecting_picks_the_only_page_and_subscribes_it_to_leads(client, owner_h, seeded, fm):
    assert _connect(client, owner_h).status_code == 303
    body = client.get("/meta-ads/status", headers=owner_h).json()
    assert body["page_id"] == PAGE and body["instagram_username"] == "balaji.realty"
    assert body["leads_live"] is True
    assert fm.subscribed == ["leadgen"]


# -------------------------------------------------------------------- webhook


def test_webhook_handshake_checks_the_verify_token(client, fm):
    ok = client.get("/internal/meta/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1234"})
    assert ok.status_code == 200 and ok.text == "1234"
    bad = client.get("/internal/meta/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1234"})
    assert bad.status_code == 403


def test_unsigned_or_forged_webhook_bodies_are_refused(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    assert client.post("/internal/meta/webhook", content=_event()).status_code == 403
    forged = client.post("/internal/meta/webhook", content=_event(), headers=_sign(_event(), "wrong"))
    assert forged.status_code == 403
    assert _contacts() == []


def test_a_signed_lead_becomes_a_contact_owned_by_the_connected_user(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    body = _event()
    res = client.post("/internal/meta/webhook", content=body, headers=_sign(body))
    assert res.status_code == 200 and res.json() == {"accepted": 1}
    (c,) = _contacts()
    assert (c.first_name, c.last_name, c.bhk) == ("Rohan", "Mehta", 3)
    assert c.campaign == "Powai 2BHK leads" and c.stage == "new" and c.is_lead
    assert "Malad West" in c.preferred_locations


def test_redelivery_does_not_create_a_second_contact(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    body = _event()
    client.post("/internal/meta/webhook", content=body, headers=_sign(body))
    again = client.post("/internal/meta/webhook", content=body, headers=_sign(body))
    assert again.json() == {"accepted": 0}
    assert len(_contacts()) == 1


def test_the_same_phone_in_a_new_lead_links_instead_of_duplicating(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    b1 = _event()
    client.post("/internal/meta/webhook", content=b1, headers=_sign(b1))
    fm.leads["L2"] = {**LEAD, "id": "L2", "field_data": [
        {"name": "full_name", "values": ["R. Mehta"]}, {"name": "phone_number", "values": ["09820011223"]}]}
    b2 = _event("L2")
    client.post("/internal/meta/webhook", content=b2, headers=_sign(b2))
    assert len(_contacts()) == 1
    rows = client.get("/meta-ads/leads/recent", headers=owner_h).json()
    assert sorted(r["status"] for r in rows) == ["created", "linked"]


def test_a_lead_for_an_unconnected_page_is_kept_and_marked_for_retry(client, owner_h, seeded, fm):
    body = _event()  # nobody has connected
    res = client.post("/internal/meta/webhook", content=body, headers=_sign(body))
    assert res.json() == {"accepted": 1}
    from sqlalchemy import select
    from app.db import SessionLocal, system_scope
    from app.models import MetaLead

    db = SessionLocal()
    with system_scope():
        (lead,) = db.execute(select(MetaLead)).scalars().all()
    db.close()
    assert lead.status == "pending" and lead.error and lead.attempts == 1


def test_sync_imports_leads_the_webhook_missed(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    res = client.post("/meta-ads/leads/sync", headers=owner_h)
    assert res.status_code == 200 and res.json()["new"] == 1
    assert len(_contacts()) == 1
    assert client.post("/meta-ads/leads/sync", headers=owner_h).json()["new"] == 0


def test_only_the_owner_can_read_or_sync_leads(client, alice_h, owner_h, seeded, fm):
    for method, path in (("get", "/meta-ads/leads/recent"), ("post", "/meta-ads/leads/sync"),
                         ("get", "/meta-ads/lead-performance"), ("get", "/meta-ads/reels/suggestions")):
        assert getattr(client, method)(path, headers=alice_h).status_code == 403


# ---------------------------------------------------------- lead performance


def test_performance_joins_spend_to_what_leads_did_in_the_crm(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    client.post("/meta-ads/leads/sync", headers=owner_h)
    (c,) = _contacts()
    client.patch(f"/contacts/{c.id}", json={"stage": "visited"}, headers=owner_h)
    body = client.get("/meta-ads/lead-performance?date_preset=maximum", headers=owner_h).json()
    row = next(r for r in body["rows"] if r["campaign_id"] == LEAD["campaign_id"])
    assert row["crm_leads"] == 1 and row["visited"] == 1 and row["qualified"] == 1
    assert row["spend"] == 1234.5 and row["cost_per_visit"] == 1234.5
    assert body["totals"]["crm_leads"] == 1 and body["failed_leads"] == 0


# --------------------------------------------------------------------- reels


def test_reels_are_ranked_and_matched_to_crm_demand(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    body = client.get("/meta-ads/reels/suggestions", headers=owner_h)
    assert body.status_code == 200, body.text
    reels = body.json()["reels"]
    assert [r["media_id"] for r in reels][0] == "9101"
    top = reels[0]
    assert top["verdict"] == "strong" and top["score"] == 100
    assert top["campaign"]["daily_budget"] == settings.meta_default_daily_budget
    weak = next(r for r in reels if r["media_id"] == "9102")
    assert weak["score"] < top["score"]
    young = next(r for r in reels if r["media_id"] == "9103")
    assert young["verdict"] == "not_enough_data" and young["campaign"] is None


def test_scoring_ranks_against_the_accounts_own_best_reel():
    reels = [
        {"media_id": "a", "caption": "", "reach": 1000, "views": 1, "likes": 10, "comments": 0, "shares": 0,
         "saved": 0, "engagement_rate": 1, "_weighted": 0.01, "permalink": None, "thumbnail_url": None, "posted_at": None},
        {"media_id": "b", "caption": "", "reach": 500, "views": 1, "likes": 10, "comments": 0, "shares": 0,
         "saved": 0, "engagement_rate": 2, "_weighted": 0.02, "permalink": None, "thumbnail_url": None, "posted_at": None},
    ]
    ranked = meta_reels.score_reels(reels)
    assert {r["media_id"]: r["score"] for r in ranked} == {"a": 75, "b": 75}


def _create(client, headers, **over):
    payload = {"form_id": FORM, "daily_budget": "500", "name": "Reel boost - Malad", "confirm": True, **over}
    return client.post("/meta-ads/reels/9101/campaign", json=payload, headers=headers)


def test_creating_a_campaign_from_a_reel_builds_everything_paused(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    res = _create(client, owner_h)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "PAUSED" and res.json()["campaign_id"] == "c-1"
    kinds = {k: p for k, p in fm.created}
    assert kinds["campaigns"]["status"] == "PAUSED" and kinds["campaigns"]["objective"] == "OUTCOME_LEADS"
    assert kinds["adsets"]["status"] == "PAUSED" and kinds["adsets"]["daily_budget"] == "50000"
    assert kinds["ads"]["status"] == "PAUSED"
    assert json.loads(kinds["adsets"]["targeting"])["geo_locations"]["cities"][0]["key"] == "2418956"
    assert json.loads(kinds["adcreatives"]["call_to_action"])["value"]["lead_gen_form_id"] == FORM
    assert _audit("create")


def test_creation_needs_confirmation_and_a_form_on_this_page(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    assert _create(client, owner_h, confirm=False).status_code == 400
    assert _create(client, owner_h, form_id="999").status_code == 400
    assert client.post("/meta-ads/reels/12345/campaign", headers=owner_h, json={
        "form_id": FORM, "daily_budget": "500", "name": "Someone else's", "confirm": True}).status_code == 404
    assert fm.created == []


def test_a_failure_part_way_removes_the_half_built_campaign(client, owner_h, seeded, fm):
    _connect(client, owner_h)
    fm.fail_creative = True
    res = _create(client, owner_h)
    assert res.status_code == 502
    assert fm.deleted == ["c-1"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("₹2_cr_to_₹4_cr", (20_000_000, 40_000_000)),
        ("2 cr - 4 cr", (20_000_000, 40_000_000)),
        ("1-2 cr", (10_000_000, 20_000_000)),
        ("50_lakh_to_1_cr", (5_000_000, 10_000_000)),
        ("1.5 crore", (15_000_000, 15_000_000)),
        ("under_1_cr", (None, 10_000_000)),
        ("above 4 cr", (40_000_000, None)),
        ("not sure", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_budget_answers_become_rupee_ranges(text, expected):
    assert meta_leads.parse_budget(text) == expected


def test_a_budget_answer_fills_the_contacts_budget():
    fields = meta_leads.map_contact_fields(
        [
            {"name": "full_name", "values": ["Rahul"]},
            {"name": "what_is_your_budget?", "values": ["₹2_cr_to_₹4_cr"]},
        ]
    )
    assert (fields["budget_min"], fields["budget_max"]) == (20_000_000, 40_000_000)


def test_sync_fills_the_budget_on_leads_imported_before_budgets_were_read(client, owner_h, seeded, fm):
    from app.db import SessionLocal, system_scope

    fm.leads["L1"]["field_data"].append({"name": "what_is_your_budget?", "values": ["₹2_cr_to_₹4_cr"]})
    _connect(client, owner_h)
    client.post("/meta-ads/leads/sync", headers=owner_h)
    db = SessionLocal()
    with system_scope():
        (c,) = _contacts()
        c = db.get(type(c), c.id)
        c.budget_min = c.budget_max = None  # as the 284 earlier imports were
        db.commit()
    res = client.post("/meta-ads/leads/sync", headers=owner_h)
    assert res.json()["budgets_filled"] == 1
    (c,) = _contacts()
    assert (int(c.budget_min), int(c.budget_max)) == (20_000_000, 40_000_000)
    assert client.post("/meta-ads/leads/sync", headers=owner_h).json()["budgets_filled"] == 0
    db.close()
