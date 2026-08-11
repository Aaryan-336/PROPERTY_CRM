"""Tests for importing a cold-calling list from Excel/CSV.

Two things are worth testing here and they fail differently:

* **Parsing** — pure, and tested against the shapes these files actually
  arrive in. A misread phone column silently produces a queue of unreachable
  numbers, which nobody notices until a caller has worked through it.
* **Assignment** — an imported lead only reaches a caller because `owner_id`
  puts it in their scope. That link is the whole feature, so it is asserted
  through `/call-queue` rather than by inspecting rows.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.lead_import import distribute, parse_lead_file


def sheet(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_reads_a_plain_sheet():
    result = parse_lead_file(
        sheet([["Name", "Mobile"], ["Rakesh Sharma", 9876543210]]), "l.xlsx"
    )
    row = result.rows[0]
    assert row.first_name == "Rakesh" and row.last_name == "Sharma"
    assert row.phone == "9876543210"


def test_finds_the_header_under_title_rows():
    """Exports routinely carry a title and a blank line above the real header."""
    result = parse_lead_file(
        sheet(
            [
                ["Andheri Leads - March 2026"],
                [],
                ["Client Name", "Contact No.", "Area"],
                ["Anil Verma", "098765 43210", "Andheri West"],
            ]
        ),
        "l.xlsx",
    )
    assert result.detected_columns["phone"] == "Contact No."
    assert result.rows[0].phone == "9876543210"
    assert result.rows[0].location == "Andheri West"


def test_sniffs_columns_when_there_is_no_header():
    """A hand-typed list often has no header at all — fall back to values."""
    result = parse_lead_file(
        sheet([["Manish Mehta", "9847562439"], ["Divya Banerjee", "9706216597"]]),
        "l.xlsx",
    )
    assert result.header_row is None
    assert [r.phone for r in result.rows] == ["9847562439", "9706216597"]
    assert result.rows[0].display_name == "Manish Mehta"


def test_excel_numeric_phone_does_not_gain_a_decimal():
    """A number typed without formatting round-trips as a float.

    Left alone, `9876543210.0` reaches the phone normalizer as twelve digits
    and the last four are wrong — the number dials, and reaches a stranger.
    """
    result = parse_lead_file(sheet([["Name", "Phone"], ["A B", 9876543210.0]]), "l.xlsx")
    assert result.rows[0].phone == "9876543210"


@pytest.mark.parametrize(
    "written",
    ["+91 98765 43210", "098765-43210", "9876543210", "+919876543210", "91 9876543210"],
)
def test_phone_formats_collapse_to_one_number(written):
    result = parse_lead_file(sheet([["Name", "Mobile"], ["A B", written]]), "l.xlsx")
    assert result.rows[0].phone == "9876543210"


def test_separate_first_and_last_name_columns():
    result = parse_lead_file(
        sheet([["First Name", "Last Name", "Ph"], ["Kavita", "Iyer", "9812538949"]]),
        "l.xlsx",
    )
    assert result.rows[0].first_name == "Kavita"
    assert result.rows[0].last_name == "Iyer"


def test_middle_names_are_kept():
    result = parse_lead_file(
        sheet([["Name", "Mobile"], ["Rakesh Kumar Sharma", "9812538949"]]), "l.xlsx"
    )
    assert result.rows[0].last_name == "Kumar Sharma"


def test_rows_without_a_usable_number_are_rejected_with_a_reason():
    result = parse_lead_file(
        sheet([["Name", "Mobile"], ["No Phone", "not-a-number"]]), "l.xlsx"
    )
    assert not result.rows[0].usable
    assert "phone" in result.rows[0].problem


def test_repeated_number_within_one_file_is_flagged():
    """Merged exports list the same lead twice; importing both gives a caller
    the same person to ring on two separate rows."""
    result = parse_lead_file(
        sheet(
            [
                ["Name", "Mobile"],
                ["Tanvi Gupta", "9812538949"],
                ["T Gupta", "+91 98125 38949"],
            ]
        ),
        "l.xlsx",
    )
    assert result.rows[0].usable
    assert not result.rows[1].usable
    assert "duplicate" in result.rows[1].problem


def test_missing_phone_column_warns_rather_than_importing_junk():
    result = parse_lead_file(sheet([["Name", "City"], ["A B", "Thane"]]), "l.xlsx")
    assert any("phone" in w.lower() for w in result.warnings)
    assert result.usable_rows == []


def test_csv_with_semicolons_is_handled():
    data = b"Customer Name;Mobile No;City\nRahul Desai;+919812345678;Thane\n"
    result = parse_lead_file(data, "list.csv")
    assert result.rows[0].phone == "9812345678"
    assert result.rows[0].location == "Thane"


def test_legacy_xls_is_refused_with_advice():
    with pytest.raises(ValueError, match="re-save"):
        parse_lead_file(b"\xd0\xcf\x11\xe0rubbish", "old.xls")


def test_distribute_deals_round_robin():
    """Contiguous slices would hand one caller every premium lead when the
    file happens to be sorted by budget."""
    assert distribute([1, 2, 3, 4, 5], 2) == [[1, 3, 5], [2, 4]]
    assert distribute([1, 2], 3) == [[1], [2], []]
    assert distribute([1], 0) == []


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


def _upload(rows):
    return {"file": ("leads.xlsx", sheet(rows), "application/vnd.ms-excel")}


LIST = [
    ["Name", "Mobile", "Area"],
    ["Import One", "9700000001", "Powai"],
    ["Import Two", "9700000002", "Thane"],
    ["Import Three", "9700000003", "Vashi"],
    ["Import Four", "9700000004", "Chembur"],
]


def test_preview_writes_nothing(client, owner_h):
    before = client.get("/contacts?limit=1", headers=owner_h).json()["total"]
    resp = client.post(
        "/contacts/bulk-import/preview", files=_upload(LIST), headers=owner_h
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 4
    assert body["detected_columns"]["phone"] == "Mobile"
    after = client.get("/contacts?limit=1", headers=owner_h).json()["total"]
    assert before == after, "preview must not create contacts"


def test_staff_cannot_import(client, alice_h, carol_h):
    """ROLES_PERMISSIONS.md gives bulk import to the Owner only."""
    for headers in (alice_h, carol_h):
        assert (
            client.post(
                "/contacts/bulk-import", files=_upload(LIST), headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/contacts/bulk-import/preview", files=_upload(LIST), headers=headers
            ).status_code
            == 403
        )


def test_import_assigns_round_robin_across_selected_callers(
    client, owner_h, seeded
):
    rows = [
        ["Name", "Mobile"],
        ["Split A", "9710000001"],
        ["Split B", "9710000002"],
        ["Split C", "9710000003"],
    ]
    resp = client.post(
        "/contacts/bulk-import",
        files=_upload(rows),
        data={"assign_to": [str(seeded["carol_id"]), str(seeded["alice_id"])]},
        headers=owner_h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 3
    assigned = {a["user_id"]: a["assigned"] for a in body["assignments"]}
    assert assigned[seeded["carol_id"]] == 2
    assert assigned[seeded["alice_id"]] == 1


def test_imported_leads_appear_in_that_callers_queue(client, owner_h, carol_h, seeded):
    """The point of the feature: assignment is what fills the call queue.

    `/call-queue` is scoped to the contacts a caller owns, so setting owner_id
    is the whole mechanism — there is no separate queue to populate.
    """
    rows = [["Name", "Mobile"], ["Queue Lands", "9720000001"]]
    client.post(
        "/contacts/bulk-import",
        files=_upload(rows),
        data={"assign_to": [str(seeded["carol_id"])]},
        headers=owner_h,
    )
    queue = client.get("/call-queue?limit=50", headers=carol_h).json()
    names = [item["contact"]["first_name"] for item in queue]
    assert "Queue" in names or any("Queue" in n for n in names)


def test_import_does_not_leak_into_another_callers_queue(
    client, owner_h, alice_h, seeded
):
    rows = [["Name", "Mobile"], ["Only Carol", "9730000001"]]
    client.post(
        "/contacts/bulk-import",
        files=_upload(rows),
        data={"assign_to": [str(seeded["carol_id"])]},
        headers=owner_h,
    )
    alice_leads = client.get("/contacts?limit=50", headers=alice_h).json()["items"]
    assert not any(c["first_name"] == "Only" for c in alice_leads)


def test_reimporting_the_same_file_adds_nothing(client, owner_h, seeded):
    """Owners re-upload the same list. Without dedup a caller gets the same
    person to ring three times."""
    rows = [["Name", "Mobile"], ["Repeat Person", "9740000001"]]
    payload = {"assign_to": [str(seeded["carol_id"])]}

    first = client.post(
        "/contacts/bulk-import", files=_upload(rows), data=payload, headers=owner_h
    ).json()
    second = client.post(
        "/contacts/bulk-import", files=_upload(rows), data=payload, headers=owner_h
    ).json()

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["duplicates"] == 1


def test_import_rejects_an_unknown_assignee(client, owner_h):
    resp = client.post(
        "/contacts/bulk-import",
        files=_upload(LIST),
        data={"assign_to": ["999999"]},
        headers=owner_h,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown_user"


def test_import_is_audited_with_counts_and_recipients(client, owner_h, seeded):
    rows = [["Name", "Mobile"], ["Audited Lead", "9750000001"]]
    client.post(
        "/contacts/bulk-import",
        files=_upload(rows),
        data={"assign_to": [str(seeded["carol_id"])]},
        headers=owner_h,
    )
    entries = client.get("/audit-log?limit=50", headers=owner_h).json()["items"]
    imports = [e for e in entries if e["action"] == "import"]
    assert imports, "a bulk write of contact data must be audited"
    assert imports[0]["detail"]["imported_count"] >= 1
    assert seeded["carol_id"] in imports[0]["detail"]["assigned_to"]
