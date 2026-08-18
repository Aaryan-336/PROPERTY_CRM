"""Running the extraction loop inside the API process.

Extraction belongs in its own service and normally lives there. Render has no
Background Workers on the free plan, so on that deployment the worker has
nowhere to run -- messages arrive from the gateway, sit as `pending`, and the
feed reports a healthy connection that produces no inventory whatsoever.

These are about the switch and its guards, not about extraction itself, which
tests/test_extraction_client.py already covers.
"""

from __future__ import annotations

import app.main as main_module
from app.config import settings


def test_it_is_off_unless_asked_for(monkeypatch):
    """A firm on a paid plan should run the worker properly, where it can be
    restarted without bouncing the API."""
    assert settings.extraction_in_api is False


def test_enabling_it_starts_the_shared_loop(monkeypatch):
    """The same run_forever the standalone worker uses.

    A second implementation would drift, and the one that drifted would be the
    one nobody watches.
    """
    started = {}

    class FakeThread:
        def __init__(self, target, args, name, daemon):
            started["target"] = target
            started["args"] = args
            started["daemon"] = daemon
        def start(self):
            started["started"] = True

    monkeypatch.setattr(main_module.settings, "extraction_in_api", True)
    monkeypatch.setattr(main_module, "threading", type("T", (), {"Thread": FakeThread}))
    monkeypatch.setattr(
        main_module, "Extractor", lambda: type("E", (), {"available": True})()
    )

    import asyncio

    async def drive():
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(drive())

    assert started.get("started") is True
    assert started["target"] is main_module.run_forever
    # Daemon: shutdown must never block on an in-flight extraction.
    assert started["daemon"] is True


def test_it_says_so_when_there_is_no_model_key(monkeypatch, caplog):
    """The failure this replaces was silent.

    Without a key the API is fine and the feed is not, and an empty inventory
    gives no reason on its own.
    """
    monkeypatch.setattr(main_module.settings, "extraction_in_api", True)
    monkeypatch.setattr(
        main_module, "Extractor", lambda: type("E", (), {"available": False})()
    )
    spawned = []
    monkeypatch.setattr(
        main_module,
        "threading",
        type("T", (), {"Thread": lambda **kw: spawned.append(kw)}),
    )

    import asyncio

    async def drive():
        async with main_module.lifespan(main_module.app):
            pass

    with caplog.at_level("WARNING"):
        asyncio.run(drive())

    assert spawned == [], "must not spawn a worker that cannot extract"
    assert any("GROQ_API_KEY" in r.message for r in caplog.records)
