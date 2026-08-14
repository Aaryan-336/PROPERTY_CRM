"""Pairing WhatsApp from the browser.

The QR here is a live credential: scanning it links a WhatsApp account to this
deployment. So the interesting tests are about who can read one, and about not
showing a code that has already rotated — which fails on the phone with no
explanation and looks like the feature is broken.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from app.config import settings


def _signed(client, payload: dict):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = hmac.new(
        settings.whatsapp_ingest_secret.encode(),
        f"{ts}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/internal/whatsapp/session",
        content=body,
        headers={
            "content-type": "application/json",
            "x-balaji-signature": sig,
            "x-balaji-timestamp": ts,
        },
    )


def test_a_reported_qr_reaches_the_owners_screen(client, owner_h, seeded):
    assert _signed(client, {"state": "qr", "qr": "2@abc", "qr_ttl_seconds": 60}).status_code == 200

    body = client.get("/whatsapp/session", headers=owner_h).json()
    assert body["state"] == "qr"
    assert body["qr"] == "2@abc"
    assert body["stale"] is False


def test_an_expired_qr_is_withheld_rather_than_shown(client, owner_h, seeded):
    """WhatsApp rotates roughly every 20s.

    A spent code still renders perfectly and simply fails on the phone, which
    reads as a broken feature rather than a stale code.
    """
    _signed(client, {"state": "qr", "qr": "2@stale", "qr_ttl_seconds": 1})
    time.sleep(1.2)

    body = client.get("/whatsapp/session", headers=owner_h).json()
    assert body["qr"] is None


def test_connecting_clears_a_spent_code(client, owner_h, seeded):
    _signed(client, {"state": "qr", "qr": "2@abc", "qr_ttl_seconds": 60})
    _signed(client, {"state": "connected", "jid": "919876543210:1@s.whatsapp.net"})

    body = client.get("/whatsapp/session", headers=owner_h).json()
    assert body["state"] == "connected"
    assert body["qr"] is None, "a scanned code must not linger on screen"
    assert body["jid"].startswith("919876543210")


def test_staff_cannot_read_the_pairing_code(client, alice_h, carol_h, seeded):
    """Scanning it links an account. It is owner-only, by capability."""
    _signed(client, {"state": "qr", "qr": "2@secret", "qr_ttl_seconds": 60})
    for headers in (alice_h, carol_h):
        assert client.get("/whatsapp/session", headers=headers).status_code == 403


def test_an_unsigned_report_is_refused(client, owner_h, seeded):
    """Otherwise anyone who found the path could put their own QR in front of
    the owner and have them link the attacker's account instead."""
    res = client.post(
        "/internal/whatsapp/session",
        json={"state": "qr", "qr": "2@attacker"},
    )
    assert res.status_code == 403
    assert client.get("/whatsapp/session", headers=owner_h).json()["qr"] != "2@attacker"
