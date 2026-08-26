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
                 content: str = PAYLOAD, finish: str = "stop",
                 truncate_below: int | None = None) -> None:
        self.calls: list[dict] = []
        self.reject_schema = reject_schema
        self.error = error
        self.content = content
        self.finish = finish
        # Stand-in for a real model's behaviour: the response is cut off until
        # the request reserves enough room for it.
        self.truncate_below = truncate_below
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.reject_schema and kwargs["response_format"]["type"] == "json_schema":
            raise _SchemaRejected()
        if self.truncate_below is not None and kwargs["max_tokens"] < self.truncate_below:
            return _response(self.content[:80], "length")
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


def test_a_truncated_response_is_retried_with_more_room():
    """The bug this replaces: a truncated batch was simply given up on.

    The advice it gave -- lower the batch size -- was the opposite of the fix,
    because the budget is sized *per message*: splitting a truncated batch
    hands each half a smaller allowance than the one that had just proved too
    small. A group whose brokers post numbered lists of a dozen flats hit this
    on every batch, and the queue stopped moving.
    """
    client = FakeGroq(truncate_below=3000)
    results = _extractor(client).extract(ITEMS)

    assert len(results) == 2  # it eventually succeeded
    budgets = [c["max_tokens"] for c in client.calls]
    # Started at the estimate and climbed, rather than splitting the batch.
    assert budgets == sorted(budgets) and budgets[-1] >= 3000
    assert all(len(c["messages"]) == 2 for c in client.calls)


class _TruncatedUnderSchema(Exception):
    """How Groq actually reports a truncated response in strict-schema mode.

    Not `finish_reason == "length"`: under `json_schema` the API validates the
    completion before returning it, so output that ran out of room is refused
    as a 400 that reads like a bad prompt.
    """

    status_code = 400

    def __str__(self) -> str:
        return (
            "Error code: 400 - {'error': {'message': 'Failed to generate JSON. "
            "Please adjust your prompt.', 'code': 'json_validate_failed', "
            "'failed_generation': 'max completion tokens reached before "
            "generating a valid document'}}"
        )


def test_truncation_reported_as_a_400_is_still_truncation():
    """The signal production actually sends, and the one the first fix missed.

    Verified against the live API: a dense broadcast post under a strict schema
    comes back as `json_validate_failed`, not as a finish reason. Treated as a
    prompt problem it is neither retried with more room nor reported honestly,
    which is exactly how the queue stopped moving.
    """
    calls: list[dict] = []
    client = FakeGroq()
    real_create = client._create

    def create(**kwargs):
        calls.append(kwargs)
        if kwargs["max_tokens"] < 3000:
            raise _TruncatedUnderSchema()
        return real_create(**kwargs)

    client.chat.completions.create = create

    results = _extractor(client).extract(ITEMS)
    assert len(results) == 2
    budgets = [c["max_tokens"] for c in calls]
    assert budgets == sorted(budgets) and budgets[-1] >= 3000
    # It must not be mistaken for a schema rejection and downgraded: JSON mode
    # constrains syntax, not shape, and would hide the real problem.
    assert all(c["response_format"]["type"] == "json_schema" for c in calls)


def test_a_dense_group_does_not_rediscover_its_size_every_batch():
    """Ratcheting the estimate, like the schema downgrade before it.

    Without it, brokers who always post numbered lists cost a truncated request
    on every single batch — which on a free tier is allowance spent on nothing.
    """
    client = FakeGroq(truncate_below=3000)
    extractor = _extractor(client)

    extractor.extract(ITEMS)
    first_opening = client.calls[0]["max_tokens"]

    client.calls.clear()
    extractor.extract(ITEMS)
    second_opening = client.calls[0]["max_tokens"]

    assert second_opening > first_opening
    assert len(client.calls) == 1, "the second batch should not need a retry"


def test_the_ceiling_is_where_it_gives_up_rather_than_climbing_forever():
    """Truncation must never fall through to the parser: half a JSON document
    parses as garbage, or worse, as something."""
    from app.extraction import OUTPUT_CEILING

    client = FakeGroq(content=PAYLOAD[:80], finish="length")
    with pytest.raises(RuntimeError, match="more than"):
        _extractor(client).extract(ITEMS)

    assert max(c["max_tokens"] for c in client.calls) == OUTPUT_CEILING


def test_at_the_ceiling_it_splits_rather_than_shrinking_the_budget():
    """Only once there is no ceiling left to raise does a smaller batch help --
    and each half must keep the ceiling, not fall back to the estimate."""
    from app.extraction import OUTPUT_CEILING

    client = FakeGroq(content=PAYLOAD[:80], finish="length")
    with pytest.raises(RuntimeError):
        _extractor(client).extract(ITEMS)

    singles = [c for c in client.calls if len(c["messages"]) == 2]
    # The batch was eventually broken up, and the halves were tried at the
    # ceiling rather than at the estimate they had already outgrown.
    split_calls = [c for c in client.calls if c["max_tokens"] == OUTPUT_CEILING]
    assert len(split_calls) >= 2
    assert singles  # sanity: the batch was tried whole first


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
