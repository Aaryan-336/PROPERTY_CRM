"""The Groq call path in app/extraction.py.

The extraction *prompt* is exercised by test_whatsapp_ingestion.py through a
stub. This covers the layer underneath it — the bit that talks to Groq — which
has no coverage otherwise and three behaviours that are easy to get wrong and
expensive to get wrong quietly.
"""

from __future__ import annotations

import json
import types

import pytest

from app.config import settings
from app.extraction import (
    ExtractionBatch,
    ExtractionInput,
    ExtractionUnavailable,
    Extractor,
    _strict_schema,
)

ITEMS = [
    ExtractionInput(ref="m1", body="3bhk lodha amara thane w 1.35cr carpet 780"),
    ExtractionInput(ref="m2", body="need 3bhk in powai, client waiting"),
]

PAYLOAD = json.dumps(
    {
        "results": [
            {
                "message_ref": "m1",
                "is_listing": True,
                "reason": "advertises a specific flat",
                "listings": [
                    {
                        "listing_type": "outright",
                        "property_type": "apartment",
                        "location": "Thane West",
                        "building": "Lodha Amara",
                        "bhk": "3bhk",
                        "price": "1.35cr",
                        "area": "780",
                        "furnishing": "",
                        "contact_name": "",
                        "contact_phone": "",
                        "title": "3BHK in Lodha Amara, Thane West",
                        "confidence": "high",
                    }
                ],
            },
            {
                "message_ref": "m2",
                "is_listing": False,
                "reason": "requirement, not inventory",
                "listings": [],
            },
        ]
    }
)


def _response(content: str, finish: str = "stop"):
    return types.SimpleNamespace(
        choices=[
            types.SimpleNamespace(
                finish_reason=finish,
                message=types.SimpleNamespace(content=content),
            )
        ],
        usage=types.SimpleNamespace(prompt_tokens=900, completion_tokens=210),
    )


class FakeGroq:
    """Records the request shape and returns a canned completion."""

    def __init__(self, *, reject_schema: bool = False, error: Exception | None = None,
                 content: str = PAYLOAD, finish: str = "stop") -> None:
        self.calls: list[dict] = []
        self.reject_schema = reject_schema
        self.error = error
        self.content = content
        self.finish = finish
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.reject_schema and kwargs["response_format"]["type"] == "json_schema":
            raise _SchemaRejected()
        return _response(self.content, self.finish)


class _SchemaRejected(Exception):
    status_code = 400

    def __str__(self) -> str:
        return "response_format json_schema is not supported for this model"


def _extractor(client: FakeGroq) -> Extractor:
    e = Extractor(api_key="test-key")
    e._client = client
    return e


def test_schema_is_strict_enough_for_a_structured_output_api():
    """Every object must forbid extras and require all of its properties.

    Providers that guarantee conformance reject anything looser, and pydantic
    emits neither by default — so this is ours to get right, not pydantic's.
    """
    problems: list[str] = []

    def walk(node, path="$"):
        if isinstance(node, dict):
            if node.get("type") == "object":
                if node.get("additionalProperties") is not False:
                    problems.append(f"{path}: additionalProperties is not false")
                props = set(node.get("properties") or {})
                if props and props != set(node.get("required") or []):
                    problems.append(f"{path}: required does not cover every property")
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(_strict_schema(ExtractionBatch.model_json_schema()))
    assert problems == []


def test_extracts_a_batch_and_keeps_values_verbatim():
    client = FakeGroq()
    results = _extractor(client).extract(ITEMS)

    assert [r.message_ref for r in results] == ["m1", "m2"]
    assert results[1].is_listing is False
    listing = results[0].listings[0]
    # The whole design rests on the model copying rather than converting;
    # app/listing_normalize.py does the arithmetic, and it is tested.
    assert listing.price == "1.35cr"
    assert listing.building == "Lodha Amara"

    sent = client.calls[0]
    assert sent["temperature"] == 0, "extraction is copying; sampling variety is noise"
    assert sent["response_format"]["type"] == "json_schema"


def test_a_model_that_refuses_schemas_is_downgraded_once_not_every_batch():
    """Groq reports this as a 400 rather than advertising capability.

    The fallback must therefore be discovered, but discovering it per batch
    would mean paying a failed request forever.
    """
    client = FakeGroq(reject_schema=True)
    extractor = _extractor(client)

    assert len(extractor.extract(ITEMS)) == 2
    assert [c["response_format"]["type"] for c in client.calls] == [
        "json_schema",
        "json_object",
    ]

    # JSON mode constrains syntax, not shape, so the schema has to move into
    # the prompt or the response is valid JSON of the wrong form.
    assert "schema" in client.calls[-1]["messages"][0]["content"].lower()

    client.calls.clear()
    extractor.extract(ITEMS)
    assert [c["response_format"]["type"] for c in client.calls] == ["json_object"]


def test_auth_failure_is_not_mistaken_for_a_schema_problem():
    """Retrying a 401 in JSON mode would double the load and bury the real error."""

    class Unauthorized(Exception):
        status_code = 401

        def __str__(self) -> str:
            return "invalid api key"

    client = FakeGroq(error=Unauthorized())
    with pytest.raises(Unauthorized):
        _extractor(client).extract(ITEMS)
    assert len(client.calls) == 1


def test_truncated_output_raises_rather_than_half_parsing():
    """A batch cut off at max_tokens must be retried, not marked processed."""
    client = FakeGroq(content=PAYLOAD[:80], finish="length")
    with pytest.raises(RuntimeError, match="output limit"):
        _extractor(client).extract(ITEMS)


def test_unparseable_output_raises():
    client = FakeGroq(content="Sure! Here are the listings:")
    with pytest.raises(RuntimeError, match="unparseable"):
        _extractor(client).extract(ITEMS)


def test_no_credentials_reports_unavailable_instead_of_crashing(monkeypatch):
    """The worker checks this on startup so it says "not configured" once,
    rather than burning the backlog marking every message failed."""
    # Both sources, because there are two: the process environment (how a host
    # like Render supplies it) and settings, loaded from backend/.env (how a
    # developer does). Clearing only the environment used to pass while a real
    # key sat in .env, which is the mirror image of the bug this now guards --
    # a key in .env that the extractor could not see.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(settings, "groq_api_key", "")
    extractor = Extractor()
    assert extractor.available is False
    with pytest.raises(ExtractionUnavailable, match="GROQ_API_KEY"):
        extractor.extract(ITEMS)


def test_an_empty_batch_costs_nothing():
    client = FakeGroq()
    assert _extractor(client).extract([]) == []
    assert client.calls == []


def test_a_key_in_dotenv_is_actually_used(monkeypatch):
    """The bug that silently stopped the whole WhatsApp feed.

    config.py calls backend/.env "the single place to configure the backend",
    and pydantic loads it into settings -- but nothing exports those lines into
    the process environment, so os.getenv never saw them. A correctly
    configured GROQ_API_KEY produced an extractor that reported itself
    unconfigured: messages arrived, piled up as `pending`, and the Inventory
    feed showed a healthy connection and no listings, with nothing anywhere
    saying why.
    """
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(settings, "groq_api_key", "gsk_from_dotenv")

    assert Extractor()._api_key == "gsk_from_dotenv"


def test_the_environment_still_wins_where_there_is_no_dotenv(monkeypatch):
    """Hosts like Render set real environment variables and ship no .env."""
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_from_environment")

    assert Extractor()._api_key == "gsk_from_environment"


def test_an_oversized_batch_is_split_rather_than_failed(monkeypatch):
    """Groq counts reserved completion tokens against the per-minute allowance,
    so a whole batch can exceed a free account's budget. Waiting does not help
    -- the batch is the same size next minute -- so it is halved instead. Before
    this, every batch failed identically and for ever."""
    from app.extraction import _is_too_large

    class TooLarge(Exception):
        status_code = 413
        def __str__(self):
            return (
                "Request too large for model X on tokens per minute (TPM): "
                "Limit 8000, Requested 17759, please reduce your message size"
            )

    class OrdinaryRateLimit(Exception):
        status_code = 429
        def __str__(self):
            return "Rate limit reached for requests per minute"

    assert _is_too_large(TooLarge()) is True
    # A plain rate limit is a wait, not a split: halving would double the number
    # of requests against the very limit being hit.
    assert _is_too_large(OrdinaryRateLimit()) is False
    assert _is_too_large(RuntimeError("something else")) is False
