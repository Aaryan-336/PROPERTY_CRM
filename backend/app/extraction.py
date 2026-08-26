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
import re
import time
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

# How many output tokens to reserve, per message in the batch.
#
# This cannot simply be the model's maximum. Groq bills *reserved* completion
# tokens against the per-minute allowance, so a flat 16000 ceiling made a
# one-message batch cost ~17.7k tokens and get a 413 on a free account whose
# whole budget is 8000 a minute -- every extraction failing while the feed
# reported a healthy connection.
#
# So it is an estimate, sized for the common case: one flat, a few hundred
# tokens of JSON. The estimate is wrong often enough to matter -- brokers post
# a numbered list of a dozen flats in a single message, which is precisely the
# format this module exists to read -- and being wrong shows up as a truncated
# response rather than an error. `Extractor.extract` raises the ceiling and
# retries when that happens, rather than guessing high for every batch and
# making the common case pay for the rare one.
OUTPUT_PER_ITEM = 700
# Headroom for the JSON envelope around the listings themselves.
OUTPUT_ENVELOPE = 600
# The hard stop. Past here, splitting the batch is the only remaining move.
OUTPUT_CEILING = 16000
# How high the *remembered* per-message estimate may ratchet.
#
# A group whose brokers all post numbered lists should not rediscover that on
# every batch, paying a truncated request each time -- so a truncation raises
# the opening estimate for subsequent batches, the same way a schema rejection
# is remembered for the life of the process. Capped, because reserved tokens
# count against the per-minute allowance: left uncapped, one freak message
# would make every later batch reserve the maximum and get refused.
OUTPUT_PER_ITEM_CAP = 2800


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

When in doubt about whether the message is inventory at all, mark it false. A \
false listing pollutes the inventory the whole firm searches.

That caution applies to `is_listing` ONLY. Once a message *is* inventory, be \
exhaustive: emit every flat in it. Dropping flats from a real listing message \
is not caution, it is data loss.

## Multiple properties per message — read this twice

Most listing messages in these groups advertise SEVERAL flats, not one. A \
broker posts their whole available stock in a single message. Emit ONE ENTRY \
PER FLAT. Returning one entry for a message that listed nine flats loses eight \
flats, and that is the single most damaging mistake you can make here.

They are separated in every imaginable way, and you must handle all of them:
- numbered: "1) ... 2) ... 3)" or "1. ... 2. ..."
- bulleted, dashed, arrowed, or emoji-prefixed lines
- separated by blank lines, dashes, or a row of underscores
- simply one flat per line under a heading like "AVAILABLE RENTAL FLATS"
- a single line listing configurations in one tower: "2BHK 1.1cr / 3BHK 1.6cr \
in Oberoi Splendor" is TWO properties, not one

A shared heading, locality, building, broker name or phone number at the top \
or bottom of the message applies to every flat under it. Repeat those shared \
values on each entry rather than emitting them once.

Before you finish a message, count the flats it mentions and check you have \
emitted that many entries.

## Pre-leased and pre-rented investments

A message offering a "pre-leased", "pre-rented" or "tenanted" property is \
selling the property, NOT letting it. `listing_type` is "outright". The tenant, \
the rent, the lock-in and the escalation clause are what the buyer is buying -- \
they describe the income, not the transaction.

These messages are full of rent language and almost nothing else, so they are \
easy to read backwards. In one:

    Pre-Leased Shop - Outright
    Tenant: Iron Course Gym
    Rent: 10.50 Lac/month
    Lock-in: 5 Years
    Escalation: 12% every 3 years
    Expected Price: 33 Cr

`listing_type` is "outright" and `price` is "33 Cr". It is NOT "10.50 Lac".

**`price` is always what a buyer pays to own the property.** Take it from \
"Asking Price", "Expected Price", "Outright Price", "Price" or "Quoted". Never \
put a monthly rent in `price` for one of these, however many times the message \
says the word rent. A pre-leased listing that reaches inventory at its monthly \
rent is off by two orders of magnitude and looks like a bargain that does not \
exist.

One message of these commonly holds a numbered list of eight or nine separate \
investments. Every one is its own property.

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


class RateLimited(Exception):
    """Every model on the key has hit its allowance.

    Separate from an ordinary failure because the response has to be different.
    Nothing is wrong with the messages, so charging them an attempt would fail
    a perfectly good backlog after three busy minutes -- the same mistake as
    charging a message for the host suspending mid-batch.
    """

    def __init__(self, retry_after: float, message: str) -> None:
        super().__init__(message)
        # Clamped: a header asking for an hour would stall the feed, and one
        # asking for nothing would spin.
        self.retry_after = max(5.0, min(float(retry_after), 300.0))


class ExtractionUnavailable(RuntimeError):
    """No API key configured, or the SDK is not installed."""


# Groq deprecates and renames models fairly often, so this is a starting point
# rather than a commitment -- override with EXTRACTION_MODEL when it retires.
# A 70B-class instruction-following model is the right size here: the task is
# structured copying out of messy text, which does not need a frontier model,
# and Groq's speed is what makes a per-message batch cheap enough to run
# continuously.
# Tried in order, and the order is deliberate: quality first, then two models
# that measured just as well on real broadcast posts from these groups and
# answered faster. They are separate entries because Groq meters *per model* --
# each has its own tokens-per-minute and requests-per-day bucket on the same
# key -- so a model that has hit its allowance costs nothing but a move to the
# next name in this list.
#
# Checked against the live API: all three read a ten-flat post correctly.
# `llama-3.3-70b-versatile` is not here because Groq has retired every Llama
# chat model; the only `meta-llama/*` entries left are prompt-injection
# classifiers, which cannot do extraction.
DEFAULT_MODEL = "openai/gpt-oss-120b,openai/gpt-oss-20b,qwen/qwen3.8-27b"


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
        configured = (
            model or settings.extraction_model or os.getenv("EXTRACTION_MODEL")
            or DEFAULT_MODEL
        )
        # A comma-separated list, tried in order. One name is still a valid
        # list of one, so an existing EXTRACTION_MODEL keeps working.
        #
        # The list exists because Groq's limits are *per model*: every model on
        # a free key gets its own 8,000-tokens-a-minute and 1,000-requests-a-day
        # bucket. With one model the feed simply stops for the rest of the
        # minute; with three it moves to the next bucket and keeps going. This
        # is not a way around the limits, it is the limits used as published --
        # and it does not replace a paid tier, it just stops a free one falling
        # over at the first burst.
        self._models = [m.strip() for m in configured.split(",") if m.strip()]
        self.model = self._models[0]
        self._api_key = api_key or settings.groq_api_key or os.getenv("GROQ_API_KEY")
        self._client = None
        # Whether each model accepts a strict json_schema. Per model, not
        # shared: one model refusing schemas must not silently downgrade the
        # rest to the weaker JSON mode.
        default_mode = (
            settings.extraction_schema_mode
            or os.getenv("EXTRACTION_SCHEMA_MODE")
            or "auto"
        )
        self._schema_modes = {m: default_mode for m in self._models}
        # Model -> monotonic time before which it is not worth asking again.
        # A rate-limited model that is retried every batch spends a request
        # from its daily allowance to be told the same thing.
        self._cooldowns: dict[str, float] = {}
        # Opening estimate of output tokens per message, raised when a batch
        # comes back truncated and kept for the life of the process. See
        # OUTPUT_PER_ITEM.
        self._per_item = OUTPUT_PER_ITEM

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

    def _response_format(self, model: str) -> dict:
        if self._schema_modes.get(model) == "json_object":
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
        """Extract one batch, moving to another model rather than giving up.

        Raises on transport/API failure so the worker can retry the batch rather
        than silently marking messages processed. ``RateLimited`` is the one
        exception the caller should treat differently: it means nothing was
        wrong with these messages, so they must not be charged an attempt for
        it.
        """
        if not items:
            return []
        client = self._ensure_client()
        budget = self._budget_for(items)

        cooling: list[float] = []
        for model in self._models:
            resting = self._cooldowns.get(model, 0.0) - time.monotonic()
            if resting > 0:
                # Asking a model that just refused costs a request from its
                # daily allowance to be told the same thing.
                cooling.append(resting)
                continue
            try:
                return self._extract(client, model, items, budget)
            except RateLimited as exc:
                self._cooldowns[model] = time.monotonic() + exc.retry_after
                cooling.append(exc.retry_after)
                log.warning(
                    "%s is rate limited for ~%.0fs; trying the next model",
                    model,
                    exc.retry_after,
                )

        raise RateLimited(
            min(cooling) if cooling else 60.0,
            "Every configured model is rate limited: "
            + ", ".join(self._models)
            + ". Set EXTRACTION_MODEL to a comma-separated list to spread the "
            "load, or move to a paid tier.",
        )

    def _budget_for(self, items: list[ExtractionInput]) -> int:
        """Opening estimate of how much output a batch needs."""
        return min(OUTPUT_CEILING, self._per_item * len(items) + OUTPUT_ENVELOPE)

    def _remember(self, items: list[ExtractionInput], budget: int) -> None:
        """Carry what this batch needed into the next one."""
        self._per_item = min(
            OUTPUT_PER_ITEM_CAP, max(self._per_item, budget // max(1, len(items)))
        )

    def _budget_note(self, items: list[ExtractionInput], budget: int) -> str:
        return f"batch of {len(items)} at {budget} output tokens"

    def _split(
        self, client, model: str, items: list[ExtractionInput], budget: int, why: str
    ):
        """Halve the batch and extract each side."""
        half = len(items) // 2
        log.warning("%s; splitting into %d and %d", why, half, len(items) - half)
        return self._extract(client, model, items[:half], budget) + self._extract(
            client, model, items[half:], budget
        )

    def _grow_or_split(
        self, client, model: str, items: list[ExtractionInput], budget: int
    ) -> list[MessageExtraction]:
        """Respond to a response that did not fit in the room it was given.

        Raise the ceiling for the *same* messages first. Splitting is the last
        resort and not the first, because the budget is sized per message:
        splitting hands each half a smaller allowance than the one that had
        just proved insufficient.
        """
        if budget < OUTPUT_CEILING:
            raised = min(OUTPUT_CEILING, budget * 2)
            log.warning(
                "%s came back truncated; retrying at %d",
                self._budget_note(items, budget),
                raised,
            )
            self._remember(items, raised)
            return self._extract(client, model, items, raised)

        if len(items) > 1:
            # At the ceiling. Now -- and only now -- fewer messages per request
            # means more of the ceiling for each of them. The ceiling is carried
            # into both halves rather than recomputed, which would hand them a
            # smaller budget than the one that had just proved insufficient.
            return self._split(
                client,
                model,
                items,
                budget,
                f"{self._budget_note(items, budget)} truncated at the ceiling",
            )

        raise RuntimeError(
            f"One message needs more than {OUTPUT_CEILING} tokens of output to "
            "read. It is probably not an ordinary listing — a forwarded "
            "brochure, or a very long broadcast."
        )

    def _extract(
        self, client, model: str, items: list[ExtractionInput], budget: int
    ) -> list[MessageExtraction]:
        """One request, with the two ways it can be too big handled separately.

        They look alike and are not. *The request* is too big when the reserved
        tokens exceed the account's per-minute allowance -- fewer messages per
        request is the fix. *The response* is too big when the model runs out of
        room mid-JSON -- and splitting the batch makes that **worse**, because
        the budget is sized per message: four messages share 3400 tokens, but
        one message alone gets only 1300. Splitting a truncated batch shrinks
        the very allowance that was already too small.

        That is not hypothetical. It is what happened to a group whose brokers
        post numbered lists of a dozen flats: every batch truncated, the advice
        in the error message ("lower the batch size") was the opposite of the
        fix, and the queue stopped moving.

        So a truncated response raises the ceiling for the *same* messages, and
        splits only once there is no ceiling left to raise.
        """
        try:
            response = self._call(client, model, items, budget)
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
            # A plain rate limit. Not the batch's fault and not fixed by
            # making it smaller -- the allowance is per minute and per day, so
            # a smaller request refused now is still refused. Handled by the
            # caller, which moves to another model's bucket.
            if _is_rate_limited(exc):
                raise RateLimited(_retry_after(exc), str(exc)) from exc

            if _is_too_large(exc) and len(items) > 1:
                half = len(items) // 2
                return self._split(
                    client,
                    model,
                    items,
                    self._budget_for(items[:half]),
                    f"{self._budget_note(items, budget)} exceeds the token allowance",
                )

            if _is_too_large(exc):
                # One message, and the account will not reserve enough to read
                # it. Splitting is not available and waiting does not help.
                raise RuntimeError(
                    f"A single message needs {budget} tokens of output, and this "
                    "account's per-minute allowance will not reserve that much. "
                    "A paid Groq tier reads it; the free one cannot."
                ) from exc

            # A truncated response, reported as a 400 rather than as a finish
            # reason. Under a strict schema the API validates before it answers,
            # so output that ran out of room comes back as "failed to generate
            # JSON" -- the same condition as `finish_reason == "length"`, wearing
            # a different hat. Missing this was the whole bug: the request looked
            # like a bad prompt, so it was neither retried with more room nor
            # reported as what it was.
            if _is_output_truncated(exc):
                return self._grow_or_split(client, model, items, budget)

            # Model does not do strict schemas. Groq reports this as a 400
            # rather than by advertising capability, so the only way to know is
            # to be told. Downgrade once, for the life of the process, instead
            # of paying a failed request per batch forever.
            if self._schema_modes.get(model) == "auto" and _is_schema_rejection(exc):
                log.warning(
                    "model %s rejected json_schema (%s); falling back to JSON mode",
                    model,
                    exc,
                )
                self._schema_modes[model] = "json_object"
                response = self._call(client, model, items, budget)
            else:
                raise

        choice = response.choices[0]
        if choice.finish_reason == "length":
            # Silently truncated JSON parses as garbage or not at all, so this
            # must never fall through to the parser.
            return self._grow_or_split(client, model, items, budget)

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

    def _call(self, client, model: str, items: list[ExtractionInput], budget: int):
        system = SYSTEM_PROMPT
        if self._schema_modes.get(model) == "json_object":
            # JSON mode constrains the response to *valid JSON*, not to our
            # shape, so in this path the schema has to be carried in the prompt.
            # (Groq also requires the word JSON to appear in it.)
            system += (
                "\n\n## Output\n\nRespond with JSON matching this schema "
                "exactly, and nothing else:\n\n"
                + json.dumps(_strict_schema(ExtractionBatch.model_json_schema()))
            )

        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": render_batch(items)},
            ],
            response_format=self._response_format(model),
            # Extraction is copying, not composition. Nothing here benefits
            # from sampling variety, and reruns of the same backlog should
            # agree with each other.
            temperature=0,
            # Set by the caller, which raises it when a response comes back
            # truncated. See OUTPUT_PER_ITEM.
            max_tokens=budget,
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


_DURATION = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$")


def _is_rate_limited(exc: Exception) -> bool:
    """True for an ordinary allowance refusal, as opposed to an oversized one.

    Both are 429s. ``_is_too_large`` claims the oversized case first, because
    that one *is* fixed by sending less; this one is not fixed by anything the
    request can do.
    """
    return getattr(exc, "status_code", None) == 429 and not _is_too_large(exc)


def _retry_after(exc: Exception) -> float:
    """How long the API said to wait, in seconds.

    Groq answers in two places and two formats: a plain-seconds `retry-after`,
    and `x-ratelimit-reset-tokens` as a duration like "1m26.4s". Read rather
    than assumed, because guessing high stalls the feed and guessing low spends
    the daily request allowance on being refused again.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    raw = headers.get("retry-after")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    for key in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        value = headers.get(key)
        if not value:
            continue
        match = _DURATION.match(value.strip())
        if match and any(match.groups()):
            hours, minutes, seconds = (float(g or 0) for g in match.groups())
            return hours * 3600 + minutes * 60 + seconds
    return 60.0


def _is_output_truncated(exc: Exception) -> bool:
    """True when the model ran out of output room mid-document.

    Under `json_schema` the API validates the completion before returning it, so
    a truncated document is refused as a 400 instead of arriving with
    `finish_reason == "length"`. Same condition, different report, and telling
    them apart matters: one is fixed by more room, the other by a better prompt.
    """
    if getattr(exc, "status_code", None) != 400:
        return False
    text = str(exc).lower()
    return (
        "max completion tokens reached" in text
        or "json_validate_failed" in text
    )


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
