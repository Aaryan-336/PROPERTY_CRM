"""LLM extraction of property listings from free-form WhatsApp messages.

TECH_STACK.md calls this out explicitly: "this is a genuine LLM extraction
task, not a regex job, given how inconsistent listing formats are". These four
messages all describe inventory and share no structure whatsoever:

    "3bhk lodha amara thane w 1.35cr carpet 780 semi furnished 9876543210"

    "AVAILABLE FOR RENT ✅
     Building: Rustomjee Seasons
     Config: 2 BHK | 950 sqft
     Rent: 85k + 2 dep
     Bandra East — call Imran"

    "anyone has 4bhk in powai budget 4-5 cr? client waiting"   <- a requirement,
                                                                  not inventory

    "Good morning all 🙏"                                       <- chatter

So the model does the reading, and this module does everything that has to be
*consistent*:

* it decides what counts as inventory (a broker asking *for* a 4BHK is a
  requirement, and ingesting it as a listing would poison the inventory with
  flats that do not exist);
* it asks for values verbatim -- "1.2 Cr", not a number -- because the model is
  reliable at copying what it read and unreliable at arithmetic, and
  ``app/listing_normalize.py`` converts deterministically and testably;
* it batches messages per request, because a busy brokerage generates thousands
  of messages a day and the system prompt below is large. Groq has no prompt
  caching, so that prompt is paid for on every request -- batching is the only
  thing amortising it, which makes the batch size a cost decision rather than a
  throughput one.

One message can carry several listings -- brokers routinely post a numbered
list of six flats -- so the unit of extraction is the message and the output is
a list.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings

log = logging.getLogger("balaji.extraction")

# Coarse labels rather than a 0-1 number: models are far better calibrated
# choosing between three named confidence levels than emitting a float, and
# three levels is all the review queue needs.
CONFIDENCE_SCORES = {"high": 0.92, "medium": 0.68, "low": 0.4}

# Below this, a listing is published but flagged for the owner to eyeball
# rather than trusted silently. See models.REVIEW_STATES.
REVIEW_THRESHOLD = 0.6


class ExtractedListing(BaseModel):
    """One property inside one message.

    Every field is a plain string on purpose. Empty string means "the message
    did not say", which is different from a guess -- and asking the model for
    verbatim text keeps unit conversion in tested Python rather than in a
    prompt.
    """

    listing_type: Literal["rent", "outright", "unknown"] = Field(
        description=(
            "'rent' for a monthly letting, 'outright' for a sale. 'unknown' "
            "only when the message genuinely does not say and the price gives "
            "no clue."
        )
    )
    property_type: Literal[
        "apartment", "villa", "plot", "commercial", "unknown"
    ] = Field(description="Best fit. Flats are 'apartment'. Shops/offices are 'commercial'.")
    location: str = Field(
        description=(
            "Locality, suburb or neighbourhood as written, e.g. 'Andheri West', "
            "'Thane West'. Not the building name. Empty string if absent."
        )
    )
    building: str = Field(
        description=(
            "Building, society, project or tower name, e.g. 'Lodha Amara'. "
            "Empty string if the message names none."
        )
    )
    bhk: str = Field(
        description=(
            "Bedroom count exactly as written: '3BHK', '2 bhk', 'studio', "
            "'1RK'. Empty string if absent."
        )
    )
    price: str = Field(
        description=(
            "The price EXACTLY as written, including its unit: '1.2 Cr', "
            "'85k', 'Rs 45,000/-', '1,20,00,000'. Do NOT convert, round or "
            "reformat it. Empty string if absent. If a range is given, take "
            "the lower bound."
        )
    )
    area: str = Field(
        description=(
            "Area exactly as written with its unit: '780 sqft', '100 sq yd'. "
            "Prefer carpet area when several are given. Empty string if absent."
        )
    )
    furnishing: str = Field(
        description="As written: 'furnished', 'semi furnished', 'unfurnished'. Empty if absent."
    )
    contact_name: str = Field(
        description="Name of the person to contact about this flat. Empty if absent."
    )
    contact_phone: str = Field(
        description="Phone number in the message, digits as written. Empty if absent."
    )
    title: str = Field(
        description=(
            "A short factual label you compose, e.g. '3BHK in Lodha Amara, "
            "Thane West'. Never invent details that are not in the message."
        )
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description=(
            "How sure you are this is a real, correctly-parsed listing. 'low' "
            "when the message is fragmentary or you had to infer key fields."
        )
    )


class MessageExtraction(BaseModel):
    """The verdict on one message."""

    message_ref: str = Field(
        description="Copy the ref of the message this refers to, exactly."
    )
    is_listing: bool = Field(
        description=(
            "True only if the message ADVERTISES one or more specific "
            "properties that are available. False for requirements/wanted "
            "posts, greetings, chatter, questions, or replies."
        )
    )
    reason: str = Field(
        description="One short clause explaining the is_listing decision."
    )
    listings: list[ExtractedListing] = Field(
        description="One entry per distinct property advertised. Empty when is_listing is false."
    )


class ExtractionBatch(BaseModel):
    results: list[MessageExtraction] = Field(
        description="Exactly one entry per input message, in the same order."
    )


SYSTEM_PROMPT = """\
You extract real-estate inventory from messages posted in Indian broker \
WhatsApp groups, for a brokerage that is aggregating those groups into one \
searchable inventory.

You will be given a batch of messages. Return exactly one result per message, \
in the order given, echoing each message's ref.

## What counts as a listing

Mark `is_listing` true ONLY when the message advertises one or more specific \
properties that are currently available to rent or buy.

Mark it false for:
- Requirement / "wanted" posts — a broker looking FOR a property on behalf of \
a client ("need 3bhk in Powai, budget 4cr", "client looking for shop on rent"). \
These describe demand, not inventory. Ingesting them would fill the inventory \
with flats that do not exist.
- Greetings, festival wishes, thanks, stickers, emoji-only messages.
- Questions, replies, negotiations and follow-ups about a listing posted \
earlier ("is it still available?", "share photos").
- Group admin notices, rules, joining/leaving messages.
- Loan, interiors, packers-and-movers, legal or other service advertisements.
- Sold/rented-out announcements about a property no longer available.

When in doubt, mark it false. A missed listing costs one flat; a false one \
pollutes the inventory the whole firm searches.

## Multiple properties per message

Brokers routinely post several flats in one message, often numbered or \
separated by blank lines or dashes. Emit one entry per distinct property. If \
the message lists the same flat's several configurations (e.g. "2BHK 1.1cr / \
3BHK 1.6cr in same tower"), that is two properties.

## Extraction rules

- Copy prices, areas and bedroom counts VERBATIM, including units and \
punctuation, exactly as the message wrote them. Never convert, round or \
reformat. "1.2 Cr" stays "1.2 Cr". Downstream code handles the conversion and \
it is tested; your arithmetic is not.
- Never invent a field. If a message does not state the building, the building \
is an empty string. An empty string is always better than a plausible guess.
- Do not carry information between messages in the batch. Each is independent, \
even when they clearly concern the same flat.
- Locality and building are different fields. "Lodha Amara, Thane West" means \
building "Lodha Amara" and location "Thane West".
- Indian shorthand you will see constantly: Cr = crore, L / lakh / lac, k = \
thousand, BHK = bedrooms-hall-kitchen, RK = room-kitchen, carpet/built-up/ \
super built-up are area measures, "dep" = deposit, "pm" = per month, \
"nego" = negotiable, "AVL"/"avl" = available.
- A price with "pm", "per month", "rent" or a deposit alongside it is a rent \
listing even if the message never says the word "rent".

## Confidence

- `high`: the message states the key facts plainly and you copied them.
- `medium`: readable but you had to interpret structure, or a key field is missing.
- `low`: fragmentary, ambiguous, or you are unsure it is inventory at all.
"""


@dataclass
class ExtractionInput:
    """One message handed to the model."""

    ref: str
    body: str
    group_name: str | None = None
    group_note: str | None = None
    sender_name: str | None = None


def render_batch(items: list[ExtractionInput]) -> str:
    """Render messages into the user turn.

    Delimited and ref-tagged rather than JSON-encoded: message bodies are full
    of quotes, newlines and emoji, and wrapping them in JSON adds an escaping
    failure mode for no benefit when the response shape is already constrained
    by the output schema.
    """
    blocks = []
    for item in items:
        header = f"<message ref={item.ref!r}"
        if item.group_name:
            header += f" group={item.group_name!r}"
        if item.sender_name:
            header += f" sender={item.sender_name!r}"
        header += ">"
        note = f"\n[group context: {item.group_note}]" if item.group_note else ""
        blocks.append(f"{header}{note}\n{item.body}\n</message>")
    return (
        f"Extract listings from these {len(items)} message(s). "
        "Return exactly one result per message, in this order.\n\n"
        + "\n\n".join(blocks)
    )


class ExtractionUnavailable(RuntimeError):
    """No API key configured, or the SDK is not installed."""


# Groq deprecates and renames models fairly often, so this is a starting point
# rather than a commitment -- override with EXTRACTION_MODEL when it retires.
# A 70B-class instruction-following model is the right size here: the task is
# structured copying out of messy text, which does not need a frontier model,
# and Groq's speed is what makes a per-message batch cheap enough to run
# continuously.
DEFAULT_MODEL = "openai/gpt-oss-120b"


def _strict_schema(schema: dict) -> dict:
    """Tighten a pydantic JSON schema until a structured-output API will take it.

    Providers that guarantee schema conformance (Groq included, following
    OpenAI's shape) refuse anything permissive: every object must forbid extra
    properties and must list all of its properties as required. Pydantic emits
    neither, because for validation purposes it does not need to.
    """
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
            props = schema.get("properties")
            if props:
                schema["required"] = list(props)
        for value in schema.values():
            _strict_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            _strict_schema(value)
    return schema


class Extractor:
    """Thin wrapper over Groq's chat completions API.

    Constructed once per worker process so the SDK client (and its connection
    pool) is reused across batches.

    Groq has no prompt caching, so unlike the previous Anthropic implementation
    the large system prompt is paid for on every batch. Batching therefore
    matters more, not less: it is what amortises that prompt across messages.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        # Read through `settings`, not straight off the environment.
        #
        # config.py calls `.env` "the single place to configure the backend",
        # and pydantic loads it into settings -- but os.getenv never sees it,
        # because nothing exports those lines into the process environment. So a
        # GROQ_API_KEY sitting correctly in backend/.env produced an extractor
        # that reported itself unconfigured, messages that piled up as
        # `pending`, and an Inventory feed showing a healthy connection and no
        # listings. Nothing in the product could say why.
        #
        # os.getenv stays as the fallback: on a host like Render these are real
        # environment variables and there is no .env file at all.
        self.model = (
            model or settings.extraction_model or os.getenv("EXTRACTION_MODEL")
            or DEFAULT_MODEL
        )
        self._api_key = api_key or settings.groq_api_key or os.getenv("GROQ_API_KEY")
        self._client = None
        # Whether this model accepts a strict json_schema. Assumed yes and
        # downgraded permanently on the first rejection -- see extract().
        self._schema_mode = (
            settings.extraction_schema_mode
            or os.getenv("EXTRACTION_SCHEMA_MODE")
            or "auto"
        )

    @property
    def available(self) -> bool:
        try:
            self._ensure_client()
        except ExtractionUnavailable:
            return False
        return True

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ExtractionUnavailable(
                "The `groq` package is not installed. "
                "Run: pip install -r requirements.txt"
            ) from exc

        if not self._api_key:
            raise ExtractionUnavailable(
                "No Groq credentials found. Set GROQ_API_KEY in backend/.env "
                "to enable extraction. Get one at https://console.groq.com/keys"
            )

        try:
            self._client = Groq(api_key=self._api_key)
        except Exception as exc:
            raise ExtractionUnavailable(f"Could not build Groq client: {exc}") from exc
        return self._client

    def _response_format(self) -> dict:
        if self._schema_mode == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction_batch",
                "strict": True,
                "schema": _strict_schema(ExtractionBatch.model_json_schema()),
            },
        }

    def extract(self, items: list[ExtractionInput]) -> list[MessageExtraction]:
        """Extract one batch. Raises on transport/API failure so the worker can
        retry the batch rather than silently marking messages processed."""
        if not items:
            return []
        client = self._ensure_client()

        try:
            response = self._call(client, items)
        except Exception as exc:
            # The batch does not fit the account's per-minute token allowance.
            #
            # Groq counts reserved completion tokens against TPM, so the ceiling
            # applies to the whole request, not to what comes back. A free
            # account gets 8000 a minute -- less than a full batch -- so every
            # batch failed identically and for ever, which from the product
            # looked like a feed that connected fine and produced nothing.
            #
            # Halving and retrying adapts to whatever tier the account is on,
            # instead of hard-coding the smallest one and making paid accounts
            # pay for the system prompt many times over.
            if _is_too_large(exc) and len(items) > 1:
                half = len(items) // 2
                log.warning(
                    "batch of %d exceeds the token allowance; splitting into %d and %d",
                    len(items),
                    half,
                    len(items) - half,
                )
                return self.extract(items[:half]) + self.extract(items[half:])

            # Model does not do strict schemas. Groq reports this as a 400
            # rather than by advertising capability, so the only way to know is
            # to be told. Downgrade once, for the life of the process, instead
            # of paying a failed request per batch forever.
            if self._schema_mode == "auto" and _is_schema_rejection(exc):
                log.warning(
                    "model %s rejected json_schema (%s); falling back to JSON mode",
                    self.model,
                    exc,
                )
                self._schema_mode = "json_object"
                response = self._call(client, items)
            else:
                raise

        choice = response.choices[0]
        if choice.finish_reason == "length":
            # Silently truncated JSON parses as garbage or not at all. Say so,
            # so the worker retries rather than marking the batch processed.
            raise RuntimeError(
                f"Extraction hit the output limit on a batch of {len(items)}. "
                "Lower WHATSAPP_EXTRACT_BATCH_SIZE."
            )

        content = choice.message.content
        if not content:
            raise RuntimeError("Extraction returned an empty response")

        try:
            parsed = ExtractionBatch.model_validate_json(content)
        except Exception as exc:
            raise RuntimeError(f"Extraction returned unparseable output: {exc}") from exc

        usage = getattr(response, "usage", None)
        if usage is not None:
            log.info(
                "extracted batch of %d: in=%s out=%s",
                len(items),
                getattr(usage, "prompt_tokens", "?"),
                getattr(usage, "completion_tokens", "?"),
            )

        return _align(items, parsed.results)

    def _call(self, client, items: list[ExtractionInput]):
        system = SYSTEM_PROMPT
        if self._schema_mode == "json_object":
            # JSON mode constrains the response to *valid JSON*, not to our
            # shape, so in this path the schema has to be carried in the prompt.
            # (Groq also requires the word JSON to appear in it.)
            system += (
                "\n\n## Output\n\nRespond with JSON matching this schema "
                "exactly, and nothing else:\n\n"
                + json.dumps(_strict_schema(ExtractionBatch.model_json_schema()))
            )

        return client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": render_batch(items)},
            ],
            response_format=self._response_format(),
            # Extraction is copying, not composition. Nothing here benefits
            # from sampling variety, and reruns of the same backlog should
            # agree with each other.
            temperature=0,
            # Sized to the batch, not a flat ceiling.
            #
            # Groq bills reserved completion tokens against the tokens-per-minute
            # allowance, so a fixed 16000 made a one-message batch cost ~17.7k
            # tokens and get a 413 on a free account whose whole budget is 8000
            # a minute. Every extraction failed, messages piled up as `pending`,
            # and the feed showed a healthy connection producing no listings.
            #
            # A message rarely yields more than one listing and a listing is a
            # few hundred tokens of JSON; 700 each plus headroom for the
            # envelope covers a dense post with several flats in it.
            max_tokens=min(16000, 700 * len(items) + 600),
        )


def _is_too_large(exc: Exception) -> bool:
    """True when the request exceeded the account's token allowance.

    Distinct from an ordinary rate limit: waiting does not help, because the
    same batch will be exactly as big next minute. Splitting is what helps.
    """
    status = getattr(exc, "status_code", None)
    if status not in (413, 429):
        return False
    text = str(exc).lower()
    return "too large" in text or "reduce your message size" in text


def _is_schema_rejection(exc: Exception) -> bool:
    """True when the API refused the request because of json_schema itself.

    Deliberately narrow: a rejection of the *schema* is worth retrying in the
    weaker mode, but an auth failure, a rate limit or a dead model is not, and
    retrying those would double the load and bury the real error.
    """
    if getattr(exc, "status_code", None) not in (400, 422):
        return False
    text = str(exc).lower()
    return any(
        term in text
        for term in ("json_schema", "response_format", "schema", "structured output")
    )


def _align(
    items: list[ExtractionInput], results: list[MessageExtraction]
) -> list[MessageExtraction]:
    """Match results back to inputs by ref, falling back to position.

    The prompt asks for one result per message in order, and the schema cannot
    enforce that. A batch that comes back short or reordered must not silently
    apply message 3's listings to message 1 -- that would attach real inventory
    to the wrong group and broker.
    """
    by_ref = {r.message_ref: r for r in results if r.message_ref}
    aligned: list[MessageExtraction] = []
    for index, item in enumerate(items):
        match = by_ref.get(item.ref)
        if match is None and index < len(results) and len(results) == len(items):
            # Same count but refs did not round-trip: positional is safe here.
            match = results[index]
        if match is None:
            log.warning("no extraction result for message ref=%s", item.ref)
            match = MessageExtraction(
                message_ref=item.ref,
                is_listing=False,
                reason="no result returned by extractor",
                listings=[],
            )
        aligned.append(match)
    return aligned


def confidence_score(label: str | None) -> float:
    return CONFIDENCE_SCORES.get(label or "", 0.5)
