"""Tests for the WhatsApp Property Feed Aggregator (Phase 3).

Four things are worth testing here, and they are tested at the level where a
bug would actually bite:

* **Normalization** -- pure functions, tested exhaustively, because a price
  misparse silently lists a ₹85,000 flat at ₹8.5 crore and nothing downstream
  can detect that.
* **Dedup** -- the decision that makes or breaks the "unified inventory"
  promise. Both directions matter: reposts must merge, and different units in
  the same tower must not.
* **The ingest webhook** -- authentication and idempotency. It is the one
  endpoint that accepts writes without a user, so it gets the most adversarial
  treatment.
* **Scoping** -- staff must not reach the feed's plumbing, per
  ROLES_PERMISSIONS.md.

The extractor is stubbed throughout. These tests are about the pipeline's
plumbing and its arithmetic; asserting on live model output would make the
suite slow, costly and flaky, and would test Anthropic rather than this code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.extraction import ExtractedListing, MessageExtraction
from app.listing_normalize import (
    normalize_furnishing,
    normalize_phone,
    normalize_price,
    parse_area,
    parse_bhk,
)

SECRET = "test-gateway-secret"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,listing_type,expected",
    [
        # Explicit units, the easy majority.
        ("1.2 Cr", "outright", 12_000_000),
        ("₹1.2Cr", "outright", 12_000_000),
        ("2.5 cr", "outright", 25_000_000),
        ("45 lakh", "outright", 4_500_000),
        ("85k", "rent", 85_000),
        ("Rs 85,000/-", "rent", 85_000),
        ("Rs.85000 per month", "rent", 85_000),
        # Indian digit grouping.
        ("1,20,00,000", "outright", 12_000_000),
        # Unitless shorthand: a fraction means lakh/crore, a whole number means
        # thousand/lakh. This is how brokers actually write it.
        ("1.2", "rent", 120_000),
        ("85", "rent", 85_000),
        ("45", "outright", 4_500_000),
        ("2.5", "outright", 25_000_000),
        # Absolute figures must survive the shorthand logic untouched.
        ("85000", "rent", 85_000),
        ("95000", "rent", 95_000),
        # Mislabelled magnitude: nobody rents a flat for ₹1.2 crore a month.
        ("1.2 cr", "rent", 120_000),
        ("45 k", "outright", 4_500_000),
        # Noise words must not derail the parse.
        ("2.75 Cr negotiable", "outright", 27_500_000),
        ("₹65,000/- per month", "rent", 65_000),
        (None, "rent", None),
        ("call for price", "rent", None),
    ],
)
def test_price_normalization(text, listing_type, expected):
    assert normalize_price(text, listing_type) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3BHK", 3),
        ("2 bhk", 2),
        ("4 BHK", 4),
        ("studio", 0),
        ("1RK", 0),
        # A half is a study, not a bedroom -- rounding up would merge two
        # genuinely different flats.
        ("2.5 BHK", 2),
        ("3", 3),
        # Must not read an area as a bedroom count.
        ("500 sqft", None),
        (None, None),
    ],
)
def test_bhk_parsing(text, expected):
    assert parse_bhk(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1200 sqft", 1200),
        ("1,250 sq.ft.", 1250),
        ("100 sq yd", 900),      # 1 sq yd = 9 sq ft
        ("50 sqm", 538),         # 1 sq m ~= 10.764 sq ft
        ("garbage", None),
    ],
)
def test_area_parsing(text, expected):
    assert parse_area(text) == expected


def test_phone_normalization_collapses_country_code_variants():
    # The same broker's number, written four ways in four groups.
    assert (
        normalize_phone("+91 98765 43210")
        == normalize_phone("098765-43210")
        == normalize_phone("9876543210")
        == normalize_phone("+919876543210")
        == "9876543210"
    )


def test_furnishing_semi_is_not_read_as_furnished():
    # "semi furnished" contains "furnished"; order of checks matters.
    assert normalize_furnishing("Semi Furnished") == "semi_furnished"
    assert normalize_furnishing("fully furnished") == "furnished"
    assert normalize_furnishing("Bare shell") == "unfurnished"


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def _facts(**overrides):
    from app.property_dedup import ListingFacts

    base = dict(
        listing_type="outright",
        location="Thane West",
        building="Lodha Amara",
        bhk=3,
        price=13_500_000,
        area_sqft=780,
        confidence=0.9,
    )
    base.update(overrides)
    return ListingFacts(**base)


def _property(**overrides):
    from app.models import Property

    base = dict(
        location="Thane West",
        building="Lodha Amara",
        listing_type="outright",
        bhk=3,
        price=13_500_000,
        area_sqft=780,
    )
    base.update(overrides)
    return Property(**base)


def test_repost_of_same_flat_scores_as_duplicate():
    from app.property_dedup import MERGE_THRESHOLD, score_match

    score, _ = score_match(_facts(), _property())
    assert score >= MERGE_THRESHOLD


def test_price_nudge_still_merges():
    """A repost with the price shaved 5% is the same flat, not a new one."""
    from app.property_dedup import MERGE_THRESHOLD, score_match

    score, _ = score_match(_facts(price=12_900_000), _property())
    assert score >= MERGE_THRESHOLD


def test_different_bhk_in_same_building_never_merges():
    """The 2BHK and the 3BHK in one tower are different inventory.

    This is the false-merge that would hide a real flat from every agent, so
    BHK mismatch is a hard reject rather than a scoring penalty.
    """
    from app.property_dedup import score_match

    score, reason = score_match(_facts(bhk=2), _property(bhk=3))
    assert score == 0.0
    assert "BHK" in reason


def test_large_price_gap_never_merges():
    from app.property_dedup import score_match

    score, reason = score_match(_facts(price=13_500_000), _property(price=9_000_000))
    assert score == 0.0
    assert "price" in reason


def test_rent_and_sale_of_same_flat_are_different_listings():
    from app.property_dedup import score_match

    score, reason = score_match(
        _facts(listing_type="rent", price=85_000), _property(listing_type="outright")
    )
    assert score == 0.0
    assert "listing type" in reason


def test_different_building_same_locality_does_not_merge():
    from app.property_dedup import MERGE_THRESHOLD, score_match

    score, _ = score_match(
        _facts(building="Rustomjee Seasons"), _property(building="Lodha Amara")
    )
    assert score < MERGE_THRESHOLD


def test_building_name_spelling_variants_still_match():
    """Brokers spell the same tower three ways; fuzzy matching is the point."""
    from app.property_dedup import MERGE_THRESHOLD, score_match

    for variant in ("lodha amara", "Lodha  Amara ", "Amara, Lodha"):
        score, _ = score_match(_facts(building=variant), _property())
        assert score >= MERGE_THRESHOLD, variant


def test_dedupe_key_ignores_price():
    """Price must not be in the blocking key.

    Bucketing a continuous value puts ₹1.19Cr and ₹1.21Cr in different buckets,
    so the two would never be compared -- which is exactly the repost dedup
    exists to catch.
    """
    from app.property_dedup import build_dedupe_key

    assert build_dedupe_key(_facts(price=11_900_000)) == build_dedupe_key(
        _facts(price=12_100_000)
    )


def test_merge_only_fills_gaps_and_never_overwrites():
    """A sloppy repost must not rewrite a value the firm already holds."""
    from app.property_dedup import apply_listing_to_property

    existing = _property(area_sqft=None, furnishing="furnished")
    filled = apply_listing_to_property(
        existing, _facts(area_sqft=810, furnishing="unfurnished")
    )

    assert existing.area_sqft == 810      # gap filled
    assert existing.furnishing == "furnished"  # existing value preserved
    assert "area_sqft" in filled and "furnishing" not in filled
    assert existing.last_seen_at is not None


# ---------------------------------------------------------------------------
# Ingest webhook
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str = SECRET, timestamp: str | None = None):
    ts = timestamp or str(int(time.time()))
    signature = hmac.new(
        secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {"x-balaji-signature": signature, "x-balaji-timestamp": ts}


@pytest.fixture
def ingest_secret(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "whatsapp_ingest_secret", SECRET)
    return SECRET


@pytest.fixture
def group(seeded):
    """A monitored group, created directly so the test does not depend on the
    owner's UI flow."""
    from app.db import SessionLocal, system_scope
    from app.models import WhatsAppGroup

    db = SessionLocal()
    with system_scope():
        existing = (
            db.query(WhatsAppGroup)
            .filter(WhatsAppGroup.group_jid == "120363000000000001@g.us")
            .one_or_none()
        )
        if existing is None:
            existing = WhatsAppGroup(
                group_jid="120363000000000001@g.us",
                name="Thane Brokers",
                is_active=True,
                added_by=seeded["owner_id"],
            )
            db.add(existing)
            db.commit()
        data = {"id": existing.id, "jid": existing.group_jid}
    db.close()
    return data


def _payload(group_jid: str, wa_id: str, body: str = "3bhk lodha amara 1.35cr"):
    return {
        "messages": [
            {
                "wa_message_id": wa_id,
                "group_jid": group_jid,
                "body": body,
                "sender_name": "Imran",
                "sender_jid": "919820011223@s.whatsapp.net",
            }
        ]
    }


def test_ingest_requires_a_signature(client, ingest_secret, group):
    body = json.dumps(_payload(group["jid"], "unsigned-1")).encode()
    resp = client.post("/internal/whatsapp/ingest", content=body)
    assert resp.status_code == 403


def test_ingest_rejects_a_forged_signature(client, ingest_secret, group):
    body = json.dumps(_payload(group["jid"], "forged-1")).encode()
    headers = _sign(body, secret="not-the-real-secret")
    resp = client.post("/internal/whatsapp/ingest", content=body, headers=headers)
    assert resp.status_code == 403


def test_ingest_rejects_a_tampered_body(client, ingest_secret, group):
    """Signing covers the body, so swapping the payload after signing fails."""
    signed_body = json.dumps(_payload(group["jid"], "tamper-1")).encode()
    headers = _sign(signed_body)
    other_body = json.dumps(
        _payload(group["jid"], "tamper-1", body="different content")
    ).encode()

    resp = client.post("/internal/whatsapp/ingest", content=other_body, headers=headers)
    assert resp.status_code == 403


def test_ingest_rejects_a_replayed_request(client, ingest_secret, group):
    """An old signature must not be replayable to re-inject stale listings."""
    body = json.dumps(_payload(group["jid"], "replay-1")).encode()
    stale = str(int(time.time()) - 4000)
    resp = client.post(
        "/internal/whatsapp/ingest", content=body, headers=_sign(body, timestamp=stale)
    )
    assert resp.status_code == 403


def test_ingest_accepts_a_signed_message(client, ingest_secret, group):
    body = json.dumps(_payload(group["jid"], "accept-1")).encode()
    resp = client.post("/internal/whatsapp/ingest", content=body, headers=_sign(body))
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] == 1


def test_ingest_is_idempotent_on_wa_message_id(client, ingest_secret, group):
    """The gateway replays its buffer after every reconnect.

    Without idempotency, a flaky WhatsApp session would duplicate the firm's
    entire inventory each time it recovered.
    """
    body = json.dumps(_payload(group["jid"], "idem-1")).encode()

    first = client.post("/internal/whatsapp/ingest", content=body, headers=_sign(body))
    second = client.post("/internal/whatsapp/ingest", content=body, headers=_sign(body))

    assert first.json()["accepted"] == 1
    assert second.json()["accepted"] == 0
    assert second.json()["duplicates"] == 1


def test_ingest_drops_messages_from_unknown_groups(client, ingest_secret, group):
    body = json.dumps(_payload("120363999999999999@g.us", "unknown-1")).encode()
    resp = client.post("/internal/whatsapp/ingest", content=body, headers=_sign(body))
    assert resp.json()["accepted"] == 0
    assert resp.json()["unknown_groups"] == ["120363999999999999@g.us"]


def test_ingest_drops_messages_from_a_deactivated_group(
    client, ingest_secret, group, owner_h
):
    """Turning a noisy group off in the UI stops ingest, not just display."""
    client.patch(
        f"/whatsapp/groups/{group['id']}", json={"is_active": False}, headers=owner_h
    )
    try:
        body = json.dumps(_payload(group["jid"], "inactive-1")).encode()
        resp = client.post(
            "/internal/whatsapp/ingest", content=body, headers=_sign(body)
        )
        assert resp.json()["accepted"] == 0
        assert resp.json()["unknown_groups"] == [group["jid"]]
    finally:
        client.patch(
            f"/whatsapp/groups/{group['id']}", json={"is_active": True}, headers=owner_h
        )


def test_ingest_is_disabled_when_no_secret_is_configured(client, monkeypatch, group):
    """Fail closed: an unconfigured deployment accepts nothing."""
    from app.config import settings

    monkeypatch.setattr(settings, "whatsapp_ingest_secret", "")
    body = json.dumps(_payload(group["jid"], "disabled-1")).encode()
    resp = client.post("/internal/whatsapp/ingest", content=body, headers=_sign(body))
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Role scoping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/whatsapp/groups",
        "/whatsapp/ingestion-status",
        "/whatsapp/messages",
    ],
)
def test_staff_cannot_read_the_feed_plumbing(client, alice_h, carol_h, path):
    """ROLES_PERMISSIONS.md: configuring ingestion is Owner-only.

    Which groups the firm sources from is competitive information, and the raw
    feed carries counterparty numbers the firm never chose to publish.
    """
    assert client.get(path, headers=alice_h).status_code == 403
    assert client.get(path, headers=carol_h).status_code == 403


def test_owner_can_read_the_feed_plumbing(client, owner_h, group):
    assert client.get("/whatsapp/groups", headers=owner_h).status_code == 200
    assert client.get("/whatsapp/ingestion-status", headers=owner_h).status_code == 200


def test_staff_cannot_add_a_monitored_group(client, alice_h):
    resp = client.post(
        "/whatsapp/groups",
        json={"group_jid": "1@g.us", "name": "Sneaky"},
        headers=alice_h,
    )
    assert resp.status_code == 403


def test_agents_can_read_listing_provenance(client, alice_h, seeded):
    """Agents need the posting broker's number to act on a listing, and the
    repost count tells them how live it really is.

    Cold Callers do not — they have no inventory access at all; see
    test_workflow.test_cold_caller_cannot_browse_inventory.
    """
    pid = seeded["property_id"]
    assert client.get(f"/properties/{pid}/sources", headers=alice_h).status_code == 200


# ---------------------------------------------------------------------------
# Pipeline: extraction -> dedup -> inventory
# ---------------------------------------------------------------------------


class StubExtractor:
    """Returns canned extractions keyed by message body.

    Stubbed rather than live: these tests assert on the pipeline's plumbing and
    arithmetic. Asserting on real model output would make the suite slow,
    costly and flaky, and would be testing Anthropic rather than this code.
    """

    def __init__(self, by_body: dict[str, MessageExtraction]):
        self.by_body = by_body
        self.calls = 0

    def extract(self, items):
        self.calls += 1
        out = []
        for item in items:
            canned = self.by_body.get(item.body.strip())
            if canned is None:
                out.append(
                    MessageExtraction(
                        message_ref=item.ref,
                        is_listing=False,
                        reason="stub: unrecognised",
                        listings=[],
                    )
                )
            else:
                out.append(canned.model_copy(update={"message_ref": item.ref}))
        return out


def _listing(**overrides) -> ExtractedListing:
    base = dict(
        listing_type="outright",
        property_type="apartment",
        location="Thane West",
        building="Lodha Amara",
        bhk="3BHK",
        price="1.35 Cr",
        area="780 sqft",
        furnishing="semi furnished",
        contact_name="Imran",
        contact_phone="9876543210",
        title="3BHK in Lodha Amara, Thane West",
        confidence="high",
    )
    base.update(overrides)
    return ExtractedListing(**base)


def _queue_message(group_id: int, body: str, wa_id: str) -> int:
    from app.db import SessionLocal, system_scope
    from app.models import WhatsAppMessage

    db = SessionLocal()
    with system_scope():
        message = WhatsAppMessage(
            group_id=group_id, wa_message_id=wa_id, body=body, status="pending"
        )
        db.add(message)
        db.commit()
        message_id = message.id
    db.close()
    return message_id


def _run(extractor) -> object:
    from app.db import SessionLocal
    from app.ingestion import run_batch

    db = SessionLocal()
    try:
        return run_batch(db, extractor, limit=10)
    finally:
        db.close()


def _get_message(message_id: int):
    from app.db import SessionLocal, system_scope
    from app.models import WhatsAppMessage

    db = SessionLocal()
    with system_scope():
        row = db.get(WhatsAppMessage, message_id)
        data = {
            "status": row.status,
            "listings_found": row.listings_found,
            "listings_new": row.listings_new,
            "attempts": row.attempts,
        }
    db.close()
    return data


def test_pipeline_creates_a_property_from_a_listing(group):
    body = "pipeline-create: 3bhk lodha amara 1.35cr"
    message_id = _queue_message(group["id"], body, "pipe-create-1")

    stub = StubExtractor(
        {
            body: MessageExtraction(
                message_ref="", is_listing=True, reason="listing", listings=[_listing()]
            )
        }
    )
    stats = _run(stub)

    assert stats.properties_created == 1
    assert _get_message(message_id)["status"] == "extracted"


def test_pipeline_merges_a_repost_instead_of_duplicating(group):
    """The core promise: one flat posted twice is one row in inventory."""
    from app.db import SessionLocal, system_scope
    from app.models import Property, PropertySource

    body_a = "pipeline-merge-a: 3bhk amara heights 2.15cr"
    body_b = "pipeline-merge-b: 3 bhk Amara Heights 2.1 cr call now"

    listing = _listing(building="Amara Heights", price="2.15 Cr", location="Kalyan West")
    repost = _listing(
        building="Amara Heights",
        price="2.1 Cr",
        location="Kalyan West",
        contact_name="Rakesh",
        contact_phone="9000011111",
    )

    id_a = _queue_message(group["id"], body_a, "pipe-merge-1")
    _run(StubExtractor({body_a: MessageExtraction(
        message_ref="", is_listing=True, reason="listing", listings=[listing])}))

    id_b = _queue_message(group["id"], body_b, "pipe-merge-2")
    stats = _run(StubExtractor({body_b: MessageExtraction(
        message_ref="", is_listing=True, reason="listing", listings=[repost])}))

    assert stats.properties_created == 0
    assert stats.duplicates_merged == 1
    assert _get_message(id_b)["status"] == "duplicate"

    db = SessionLocal()
    with system_scope():
        matches = (
            db.query(Property)
            .filter(Property.building == "Amara Heights")
            .filter(Property.deleted_at.is_(None))
            .all()
        )
        assert len(matches) == 1, "the repost should not have created a second row"
        # Both sightings are retained -- merging is never lossy.
        sightings = (
            db.query(PropertySource)
            .filter(PropertySource.property_id == matches[0].id)
            .all()
        )
        assert len(sightings) == 2
        assert {s.relation for s in sightings} == {"origin", "duplicate"}
    db.close()


def test_pipeline_keeps_different_bhk_in_the_same_tower_separate(group):
    from app.db import SessionLocal, system_scope
    from app.models import Property

    body_a = "pipeline-split-a: 2bhk sunrise towers 90 lakh"
    body_b = "pipeline-split-b: 3bhk sunrise towers 95 lakh"

    id_a = _queue_message(group["id"], body_a, "pipe-split-1")
    _run(StubExtractor({body_a: MessageExtraction(
        message_ref="", is_listing=True, reason="listing",
        listings=[_listing(building="Sunrise Towers", location="Vashi",
                           bhk="2BHK", price="90 lakh", area="620 sqft")])}))

    id_b = _queue_message(group["id"], body_b, "pipe-split-2")
    stats = _run(StubExtractor({body_b: MessageExtraction(
        message_ref="", is_listing=True, reason="listing",
        listings=[_listing(building="Sunrise Towers", location="Vashi",
                           bhk="3BHK", price="95 lakh", area="880 sqft")])}))

    assert stats.properties_created == 1, "a different BHK is different inventory"

    db = SessionLocal()
    with system_scope():
        rows = (
            db.query(Property)
            .filter(Property.building == "Sunrise Towers")
            .filter(Property.deleted_at.is_(None))
            .all()
        )
        assert {r.bhk for r in rows} == {2, 3}
    db.close()


def test_pipeline_ignores_a_requirement_post(group):
    """A broker asking FOR a 4BHK is demand, not inventory.

    Ingesting it would fill the searchable inventory with flats that do not
    exist -- the failure mode the prompt is most explicit about.
    """
    body = "pipeline-req: anyone has 4bhk in powai budget 4-5cr? client waiting"
    message_id = _queue_message(group["id"], body, "pipe-req-1")

    stats = _run(StubExtractor({body: MessageExtraction(
        message_ref="", is_listing=False,
        reason="requirement post, not an available listing", listings=[])}))

    assert stats.properties_created == 0
    assert stats.not_listings == 1
    assert _get_message(message_id)["status"] == "not_listing"


def test_pipeline_extracts_several_listings_from_one_message(group):
    """Brokers post numbered lists; each entry is its own property."""
    body = "pipeline-multi: 1) 1bhk kandivali 65L  2) 2bhk kandivali 98L"
    _queue_message(group["id"], body, "pipe-multi-1")

    stats = _run(StubExtractor({body: MessageExtraction(
        message_ref="", is_listing=True, reason="two listings",
        listings=[
            _listing(building="Raj Residency", location="Kandivali East",
                     bhk="1BHK", price="65 lakh", area="420 sqft"),
            _listing(building="Raj Residency", location="Kandivali East",
                     bhk="2BHK", price="98 lakh", area="640 sqft"),
        ])}))

    assert stats.listings_found == 2
    assert stats.properties_created == 2


def test_pipeline_drops_a_listing_with_no_locality(group):
    """Unsearchable inventory is noise, so it is rejected rather than stored."""
    body = "pipeline-nowhere: 3bhk available good deal"
    message_id = _queue_message(group["id"], body, "pipe-nowhere-1")

    stats = _run(StubExtractor({body: MessageExtraction(
        message_ref="", is_listing=True, reason="listing",
        listings=[_listing(location="", building="", price="1.2 Cr")])}))

    assert stats.properties_created == 0
    assert _get_message(message_id)["status"] == "not_listing"


def test_low_confidence_extraction_is_published_but_flagged(group):
    """Publishing beats withholding -- an agent would rather sanity-check a
    listing than miss a real flat. The flag is what keeps that honest."""
    from app.db import SessionLocal, system_scope
    from app.models import Property

    body = "pipeline-lowconf: 2bhk?? borivali maybe 1.1"
    _queue_message(group["id"], body, "pipe-lowconf-1")

    _run(StubExtractor({body: MessageExtraction(
        message_ref="", is_listing=True, reason="fragmentary",
        listings=[_listing(building="Hazy Heights", location="Borivali East",
                           bhk="2BHK", price="1.1 Cr", confidence="low")])}))

    db = SessionLocal()
    with system_scope():
        prop = (
            db.query(Property).filter(Property.building == "Hazy Heights").one()
        )
        assert prop.review_state == "needs_review"
        assert prop.deleted_at is None, "flagged, not hidden"
    db.close()


def test_extractor_failure_returns_messages_to_the_queue(group):
    """A transport failure must not mark messages processed."""

    class Failing:
        def extract(self, items):
            raise RuntimeError("api unreachable")

    body = "pipeline-fail: 3bhk somewhere 1cr"
    message_id = _queue_message(group["id"], body, "pipe-fail-1")

    stats = _run(Failing())

    assert stats.failures == 1
    state = _get_message(message_id)
    assert state["status"] == "pending", "should be retried, not silently dropped"
    assert state["attempts"] == 1


def test_message_stops_retrying_after_the_attempt_cap(group):
    """One malformed message must not be retried forever -- that is a bill."""
    from app.models import MAX_EXTRACTION_ATTEMPTS

    class Failing:
        def extract(self, items):
            raise RuntimeError("still broken")

    # Has to look like inventory, or the chatter prefilter settles it without
    # ever reaching the extractor -- which is correct behaviour, and not what
    # this test is about.
    body = "pipeline-poison: 2bhk poison tower 1.5cr unparseable forever"
    message_id = _queue_message(group["id"], body, "pipe-poison-1")

    for _ in range(MAX_EXTRACTION_ATTEMPTS):
        _run(Failing())

    assert _get_message(message_id)["status"] == "failed"


def test_reprocessing_a_message_does_not_inflate_the_repost_count(group):
    """Replaying history after a prompt fix must be idempotent."""
    from app.db import SessionLocal, system_scope
    from app.models import Property, PropertySource, WhatsAppMessage

    body = "pipeline-replay: 3bhk replay tower 1.5cr"
    message_id = _queue_message(group["id"], body, "pipe-replay-1")
    canned = StubExtractor({body: MessageExtraction(
        message_ref="", is_listing=True, reason="listing",
        listings=[_listing(building="Replay Tower", location="Chembur",
                           price="1.5 Cr")])})

    _run(canned)

    db = SessionLocal()
    with system_scope():
        db.get(WhatsAppMessage, message_id).status = "pending"
        db.commit()
    db.close()

    _run(canned)

    db = SessionLocal()
    with system_scope():
        prop = db.query(Property).filter(Property.building == "Replay Tower").one()
        sightings = (
            db.query(PropertySource)
            .filter(PropertySource.property_id == prop.id)
            .filter(PropertySource.message_id == message_id)
            .all()
        )
        assert len(sightings) == 1
    db.close()


# ---------------------------------------------------------------------------
# Requeuing a backlog that failed for one shared reason
# ---------------------------------------------------------------------------


def _set_status(message_id: int, status: str, attempts: int, error: str | None) -> None:
    from app.db import SessionLocal, system_scope
    from app.models import WhatsAppMessage

    db = SessionLocal()
    with system_scope():
        row = db.get(WhatsAppMessage, message_id)
        row.status, row.attempts, row.error = status, attempts, error
        db.commit()
    db.close()


def _status_of(message_id: int) -> tuple[str, int, str | None]:
    from app.db import SessionLocal, system_scope
    from app.models import WhatsAppMessage

    db = SessionLocal()
    with system_scope():
        row = db.get(WhatsAppMessage, message_id)
        out = (row.status, row.attempts, row.error)
    db.close()
    return out


def test_requeueing_failed_messages_clears_the_whole_backlog(client, owner_h, group):
    """The case retrying one at a time does not cover.

    When extraction was misconfigured or buggy, every message failed for the
    same reason. The fix lands and the backlog is still there — one press per
    message is not a recovery path.
    """
    ids = [
        _queue_message(group["id"], f"bulk-retry {i}: 2bhk andheri 85k", f"bulk-{i}")
        for i in range(3)
    ]
    for message_id in ids:
        _set_status(message_id, "failed", 3, "hit the output limit")

    resp = client.post("/whatsapp/reprocess-failed", headers=owner_h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["requeued"] >= 3

    for message_id in ids:
        status, attempts, error = _status_of(message_id)
        assert status == "pending"
        # Attempts must be reset, or a message that exhausted its retries is
        # requeued into a claim filter that will never pick it up again.
        assert attempts == 0
        assert error is None


def test_requeueing_leaves_messages_that_still_have_retries_alone(
    client, owner_h, group
):
    """A pending message is already in the queue. Resetting its attempts would
    hide a genuine retry loop instead of helping it."""
    message_id = _queue_message(group["id"], "still-trying: 1bhk malad", "still-1")
    _set_status(message_id, "pending", 2, "transient")

    client.post("/whatsapp/reprocess-failed", headers=owner_h)

    assert _status_of(message_id) == ("pending", 2, "transient")


def test_requeueing_is_owner_only(client, alice_h):
    """Same capability as the rest of the feed console."""
    assert (
        client.post("/whatsapp/reprocess-failed", headers=alice_h).status_code == 403
    )


def test_requeueing_nothing_is_not_an_error(client, owner_h):
    """The button is visible whenever failures are; pressing it twice is not a
    fault."""
    client.post("/whatsapp/reprocess-failed", headers=owner_h)
    resp = client.post("/whatsapp/reprocess-failed", headers=owner_h)
    assert resp.status_code == 200
    assert resp.json()["requeued"] == 0


# ---------------------------------------------------------------------------
# Claims whose worker never came back
# ---------------------------------------------------------------------------


def _claim_state(message_id: int) -> tuple[str, int, object]:
    from app.db import SessionLocal, system_scope
    from app.models import WhatsAppMessage

    db = SessionLocal()
    with system_scope():
        row = db.get(WhatsAppMessage, message_id)
        out = (row.status, row.attempts, row.claimed_at)
    db.close()
    return out


def _strand(message_id: int, age: timedelta) -> None:
    """Put a message where a dead worker leaves one."""
    from app.db import SessionLocal, system_scope
    from app.models import WhatsAppMessage

    db = SessionLocal()
    with system_scope():
        row = db.get(WhatsAppMessage, message_id)
        row.status = "processing"
        row.attempts = 1
        row.claimed_at = datetime.now(timezone.utc) - age
        db.commit()
    db.close()


def test_claiming_records_when_it_happened(group):
    """Without this there is nothing to tell a live batch from a corpse."""
    from app.db import SessionLocal
    from app.ingestion import claim_pending

    message_id = _queue_message(group["id"], "claim-stamp: 2bhk andheri 55k", "claim-1")
    db = SessionLocal()
    claim_pending(db, 10)
    db.close()

    status, _, claimed_at = _claim_state(message_id)
    assert status == "processing"
    assert claimed_at is not None


def test_a_stalled_claim_is_returned_to_the_queue(group):
    """The bug: `claim_pending` looks only at `pending` and the owner's retry
    only at `failed`, so a `processing` row was reachable by neither and sat on
    "Extracting" for ever."""
    from app.db import SessionLocal
    from app.ingestion import STALLED_CLAIM_AFTER, reclaim_stalled

    message_id = _queue_message(group["id"], "stalled: 3bhk powai 1.2cr", "stall-1")
    _strand(message_id, STALLED_CLAIM_AFTER + timedelta(minutes=5))

    db = SessionLocal()
    assert reclaim_stalled(db) >= 1
    db.close()

    status, attempts, claimed_at = _claim_state(message_id)
    assert status == "pending"
    assert claimed_at is None
    # The attempt is given back. A host suspending mid-batch is not the
    # message's fault, and charging it would fail good messages after three
    # deploys — which on the free plan happens in a week.
    assert attempts == 0


def test_a_batch_in_flight_is_left_alone(group):
    """Reclaiming a live claim would double the work and could double-create
    inventory."""
    from app.db import SessionLocal
    from app.ingestion import reclaim_stalled

    message_id = _queue_message(group["id"], "inflight: 2bhk malad 48k", "inflight-1")
    _strand(message_id, timedelta(seconds=30))

    db = SessionLocal()
    reclaim_stalled(db)
    db.close()

    assert _claim_state(message_id)[0] == "processing"


def test_finishing_a_message_clears_its_claim(group):
    """Otherwise every finished message looks like a claim in flight."""
    body = "clears-claim: 2bhk claim tower goregaon 62k"
    message_id = _queue_message(group["id"], body, "clearclaim-1")
    _run(StubExtractor({body: MessageExtraction(
        message_ref="", is_listing=True, reason="listing",
        listings=[_listing(building="Claim Tower", location="Goregaon East",
                           price="62k")])}))

    status, _, claimed_at = _claim_state(message_id)
    assert status in ("extracted", "duplicate")
    assert claimed_at is None


def test_the_owner_can_free_stranded_claims_when_no_worker_is_running(
    client, owner_h, group
):
    """The automatic reclaim lives in the worker. If no worker is running at
    all then nothing reclaims — and that is exactly when someone presses this."""
    from app.ingestion import STALLED_CLAIM_AFTER

    stuck = _queue_message(group["id"], "owner-frees: 1bhk vasai 18k", "ownerfree-1")
    live = _queue_message(group["id"], "owner-leaves: 1bhk virar 15k", "ownerfree-2")
    _strand(stuck, STALLED_CLAIM_AFTER + timedelta(minutes=1))
    _strand(live, timedelta(seconds=10))

    resp = client.post("/whatsapp/reprocess-failed", headers=owner_h)
    assert resp.status_code == 200, resp.text

    assert _claim_state(stuck)[0] == "pending"
    assert _claim_state(live)[0] == "processing", "a live batch must not be disturbed"


# ---------------------------------------------------------------------------
# Not paying a model call for "good morning"
# ---------------------------------------------------------------------------


def test_chatter_is_settled_without_calling_the_model(group):
    """Most group traffic is not inventory, and on a rate-limited tier every
    greeting in a batch is throughput taken from a real listing."""

    class Watcher:
        """Records what it was asked to read.

        Not a stub that refuses to be called: a batch legitimately contains
        whatever else is pending, so the assertion has to be about *this*
        message never reaching the model, not about the model being idle.
        """

        def __init__(self) -> None:
            self.seen: list[str] = []

        def extract(self, items):
            self.seen.extend(item.ref for item in items)
            return [
                MessageExtraction(
                    message_ref=item.ref,
                    is_listing=False,
                    reason="not inventory",
                    listings=[],
                )
                for item in items
            ]

    message_id = _queue_message(group["id"], "Good morning all", "chatter-1")
    watcher = Watcher()
    _run(watcher)

    assert str(message_id) not in watcher.seen
    assert _get_message(message_id)["status"] == "not_listing"


def test_anything_that_could_be_a_flat_still_reaches_the_model(group):
    """The asymmetry is brutal: a dropped listing is a flat the firm never
    sees, a kept non-listing costs one slot in a batch."""
    from app.ingestion import is_obvious_chatter

    for body in [
        "is it still available",
        "anyone has flat in andheri?",
        "9876543210",
        "2bhk",
        "AVAILABLE FOR RENTAL FLAT",
    ]:
        assert is_obvious_chatter(body) is False, body

    for body in ["Good morning all", "Thanks bhai", "please share the photos"]:
        assert is_obvious_chatter(body) is True, body


def test_a_long_message_is_never_treated_as_chatter(group):
    """Length is the cheap guard: anything substantial gets read properly."""
    from app.ingestion import is_obvious_chatter

    assert is_obvious_chatter("hello " * 40) is False


def test_a_rate_limit_does_not_cost_the_message_an_attempt(group):
    """A busy minute must not retire a perfectly good backlog.

    `attempts` exists to stop a malformed message being re-sent to the model
    for ever. A rate limit says nothing about the message, so charging it would
    fail three-quarters of a busy afternoon's inventory.
    """
    from app.extraction import RateLimited

    class Limited:
        def extract(self, items):
            raise RateLimited(30.0, "every model is rate limited")

    body = "ratelimited: 2bhk andheri west 65k"
    message_id = _queue_message(group["id"], body, "ratelimit-1")

    for _ in range(4):  # more than MAX_EXTRACTION_ATTEMPTS
        _run(Limited())

    row = _get_message(message_id)
    assert row["status"] == "pending", "must stay in the queue, not fail"
    assert row["attempts"] == 0
