"""Size, remarks, and filtering leads by what they can actually spend.

Three things the lead form gained, and one each of them has to keep doing:

* ``bhk`` has to survive a round trip *and* reach the matcher, because a size
  the matcher ignores is a field that lies to the agent who filled it in.
* ``remarks`` has to survive a round trip and stay out of every role's way that
  should not be writing it.
* The budget filter has to select on overlap rather than containment, and it
  has to leave out leads with no budget stated at all -- the two mistakes that
  would make it look broken to the person using it.

Every lead these tests create is deleted again at the end, because the database
is session-scoped and a stray 3BHK at 2Cr would quietly change what the
matching and filtering tests in other files see.
"""

from __future__ import annotations

import pytest

MARK = "PrefTest"


@pytest.fixture(autouse=True)
def clean_leads(database):
    """Remove every lead this module made, before and after it runs."""
    from app.db import SessionLocal, system_scope
    from app.models import Contact

    def purge() -> None:
        db = SessionLocal()
        with system_scope():
            db.query(Contact).filter(Contact.last_name == MARK).delete(
                synchronize_session=False
            )
            db.commit()
        db.close()

    purge()
    yield
    purge()


def make_lead(client, headers, **fields) -> dict:
    body = {"first_name": "Pref", "last_name": MARK, **fields}
    resp = client.post("/contacts?force=true", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# The fields themselves
# ---------------------------------------------------------------------------


def test_size_and_remarks_round_trip(client, owner_h):
    created = make_lead(
        client,
        owner_h,
        bhk=3,
        remarks="Wants possession before June.\nHusband decides.",
    )
    assert created["bhk"] == 3
    assert created["remarks"] == "Wants possession before June.\nHusband decides."

    fetched = client.get(f"/contacts/{created['id']}", headers=owner_h).json()
    assert fetched["bhk"] == 3
    # Line breaks are part of what was typed; flattening them would run three
    # separate notes into one sentence.
    assert "\n" in fetched["remarks"]


def test_a_lead_may_state_neither(client, owner_h):
    """Every lead in the book predates these two columns."""
    created = make_lead(client, owner_h)
    assert created["bhk"] is None
    assert created["remarks"] is None


def test_both_are_editable_and_clearable(client, owner_h):
    created = make_lead(client, owner_h, bhk=2, remarks="Old note")

    patched = client.patch(
        f"/contacts/{created['id']}",
        json={"bhk": 4, "remarks": "New note"},
        headers=owner_h,
    ).json()
    assert patched["bhk"] == 4
    assert patched["remarks"] == "New note"

    cleared = client.patch(
        f"/contacts/{created['id']}",
        json={"bhk": None, "remarks": None},
        headers=owner_h,
    ).json()
    assert cleared["bhk"] is None
    assert cleared["remarks"] is None


def test_absurd_sizes_are_refused(client, owner_h):
    resp = client.post(
        "/contacts?force=true",
        json={"first_name": "Pref", "last_name": MARK, "bhk": 99},
        headers=owner_h,
    )
    assert resp.status_code == 422


def test_a_cold_caller_cannot_rewrite_remarks(client, carol_h, seeded):
    """ROLES_PERMISSIONS.md: a Cold Caller logs call remarks, not lead ones."""
    resp = client.patch(
        f"/contacts/{seeded['carol_lead']}",
        json={"remarks": "rewritten"},
        headers=carol_h,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def ids_for(client, headers, query: str) -> set[int]:
    resp = client.get(f"/contacts?{query}&limit=50", headers=headers)
    assert resp.status_code == 200, resp.text
    return {row["id"] for row in resp.json()["items"]}


def test_bhk_filter_is_exact_below_four(client, owner_h):
    two = make_lead(client, owner_h, bhk=2)
    three = make_lead(client, owner_h, bhk=3)

    found = ids_for(client, owner_h, "bhk=2")
    assert two["id"] in found
    assert three["id"] not in found


def test_bhk_four_is_the_open_top_end(client, owner_h):
    """4 means "4 or more" on inventory, so a 5BHK lead belongs under it."""
    four = make_lead(client, owner_h, bhk=4)
    six = make_lead(client, owner_h, bhk=6)
    three = make_lead(client, owner_h, bhk=3)

    found = ids_for(client, owner_h, "bhk=4")
    assert {four["id"], six["id"]} <= found
    assert three["id"] not in found


def test_budget_band_matches_an_overlapping_range(client, owner_h):
    """A lead at 80L-1.2Cr is exactly who the 1-2Cr shortlist is for."""
    straddles = make_lead(client, owner_h, budget_min=8_000_000, budget_max=12_000_000)
    below = make_lead(client, owner_h, budget_min=3_000_000, budget_max=5_000_000)
    above = make_lead(client, owner_h, budget_min=30_000_000, budget_max=40_000_000)

    found = ids_for(client, owner_h, "budget_min=10000000&budget_max=20000000")
    assert straddles["id"] in found
    assert below["id"] not in found
    assert above["id"] not in found


def test_budget_band_leaves_out_leads_with_no_budget(client, owner_h):
    """"Unknown" is not an answer to a question about money."""
    silent = make_lead(client, owner_h)
    stated = make_lead(client, owner_h, budget_min=12_000_000)

    found = ids_for(client, owner_h, "budget_min=10000000&budget_max=20000000")
    assert stated["id"] in found
    assert silent["id"] not in found


def test_an_open_ended_budget_still_matches_above_it(client, owner_h):
    """No ceiling stated means no ceiling, not a ceiling of zero."""
    no_ceiling = make_lead(client, owner_h, budget_min=15_000_000)

    assert no_ceiling["id"] in ids_for(client, owner_h, "budget_min=100000000")


def test_the_filters_narrow_and_never_widen(client, alice_h, owner_h, seeded):
    """A filter can only cut into what the role was already allowed to see."""
    bobs = make_lead(client, owner_h, bhk=3)  # owned by the Owner, not Alice
    assert bobs["id"] not in ids_for(client, alice_h, "bhk=3")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_size_reaches_the_matcher(client, owner_h, seeded):
    """The seeded listing is a 15,000,000 apartment in Powai with no bhk set.

    A listing that never stated a size stays in -- a WhatsApp forward with no
    bedroom count is still worth a look -- but one that states the wrong size
    must not be suggested.
    """
    from app.db import SessionLocal, system_scope
    from app.models import Property

    db = SessionLocal()
    with system_scope():
        three = Property(
            title="3 BHK Pref", location="Powai", listing_type="outright",
            price=15_000_000, property_type="apartment", bhk=3,
        )
        one = Property(
            title="1 BHK Pref", location="Powai", listing_type="outright",
            price=15_000_000, property_type="apartment", bhk=1,
        )
        db.add_all([three, one])
        db.commit()
        three_id, one_id = three.id, one.id

    try:
        lead = make_lead(
            client, owner_h, bhk=3, budget_min=10_000_000, budget_max=20_000_000
        )
        matches = client.get(
            f"/contacts/{lead['id']}/matches?limit=50", headers=owner_h
        ).json()
        ids = {m["property"]["id"] for m in matches}
        assert three_id in ids
        assert one_id not in ids

        reasons = next(
            m["reasons"] for m in matches if m["property"]["id"] == three_id
        )
        assert any("3BHK" in reason for reason in reasons)
    finally:
        with system_scope():
            db.query(Property).filter(Property.id.in_([three_id, one_id])).delete(
                synchronize_session=False
            )
            db.commit()
        db.close()
