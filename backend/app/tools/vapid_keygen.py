"""Generate the VAPID keypair for Web Push.

``app/push.py`` and ``.env.example`` have both told you to run
``python -m app.tools.vapid_keygen`` since push was written; this is that
command. Push is optional — with the keys unset everything else works and
notifications simply do not fire — so this is only needed when you want them.

    python -m app.tools.vapid_keygen

Prints the three settings to paste into backend/.env. Generate once and keep
them: the public key is baked into every browser subscription, so rotating it
silently breaks push for everyone already subscribed until they re-subscribe.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(raw: bytes) -> str:
    """URL-safe base64 without padding, which is what the Web Push spec wants."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())

    private = _b64(
        key.private_numbers().private_value.to_bytes(32, "big")
    )
    public = _b64(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
    )
    return public, private


def main() -> None:
    public, private = generate()
    print("# Paste into backend/.env — generate once, then leave alone.")
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
    print("# Must be a mailto: or https: URL identifying you to the push service.")
    print("VAPID_SUBJECT=mailto:you@yourfirm.com")
    print()
    print("# The frontend needs the public key too, in web/.env.local:")
    print(f"NEXT_PUBLIC_VAPID_PUBLIC_KEY={public}")


if __name__ == "__main__":
    main()
