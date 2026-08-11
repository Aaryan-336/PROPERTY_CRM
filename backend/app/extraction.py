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
* it batches messages per request and caches the (large, stable) system prompt,
  because a busy brokerage generates thousands of messages a day and a
  per-message uncached call is the difference between a rounding error and a
  real bill.

One message can carry several listings -- brokers routinely post a numbered
list of six flats -- so the unit of extraction is the message and the output is
a list.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

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


class Extractor:
    """Thin wrapper over the Messages API.

    Constructed once per worker process so the SDK client (and its connection
    pool) is reused across batches.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        effort: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model or os.getenv("EXTRACTION_MODEL", "claude-opus-5")
        # Extraction is a scoped, well-specified task -- the kind where low
        # effort performs as well as high at a fraction of the token spend.
        # Raise it via env if a market's messages prove harder than expected.
        self.effort = effort or os.getenv("EXTRACTION_EFFORT", "low")
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None

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
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ExtractionUnavailable(
                "The `anthropic` package is not installed. "
                "Run: pip install -r requirements.txt"
            ) from exc

        # A bare client also resolves ANTHROPIC_AUTH_TOKEN or an `ant auth
        # login` profile, so an unset ANTHROPIC_API_KEY does not by itself mean
        # there are no credentials -- let the SDK do the resolving.
        try:
            client = (
                anthropic.Anthropic(api_key=self._api_key)
                if self._api_key
                else anthropic.Anthropic()
            )
        except Exception as exc:
            raise ExtractionUnavailable(f"Could not build Anthropic client: {exc}") from exc

        # Construction is lazy: with no credentials at all it succeeds here and
        # fails at request time instead. Check now, so the worker reports
        # "not configured" on startup rather than burning through the backlog
        # marking every message failed.
        if not any(
            getattr(client, attr, None)
            for attr in ("api_key", "auth_token", "credentials")
        ):
            raise ExtractionUnavailable(
                "No Anthropic credentials found. Set ANTHROPIC_API_KEY in "
                "backend/.env (or run `ant auth login`) to enable extraction."
            )

        self._client = client
        return self._client

    def extract(self, items: list[ExtractionInput]) -> list[MessageExtraction]:
        """Extract one batch. Raises on transport/API failure so the worker can
        retry the batch rather than silently marking messages processed."""
        if not items:
            return []
        client = self._ensure_client()

        response = client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # The system prompt is large, byte-stable and re-sent on
                    # every batch -- the textbook case for caching. Only the
                    # message block after it varies.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": render_batch(items)}],
            output_format=ExtractionBatch,
            output_config={"effort": self.effort},
        )

        if response.stop_reason == "refusal":
            raise RuntimeError(
                "Extraction refused by safety classifier: "
                f"{getattr(response.stop_details, 'category', None)}"
            )

        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError("Extraction returned no parseable output")

        usage = getattr(response, "usage", None)
        if usage is not None:
            log.info(
                "extracted batch of %d: in=%s out=%s cache_read=%s",
                len(items),
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", "?"),
            )

        return _align(items, parsed.results)


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
