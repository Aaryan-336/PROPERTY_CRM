"""The WhatsApp message -> inventory pipeline.

Implements ARCHITECTURE.md's "WhatsApp listing -> searchable inventory" flow
from step 3 onward (the gateway and the webhook cover 1-2):

    3. Job queued: LLM extraction -> structured fields
    4. Dedup check against existing `properties`
    5. If new: insert with `source = whatsapp_group`, `raw_message` retained
    6. If likely duplicate: attach as an additional source reference
    7. Now queryable in the unified inventory view

Everything runs under ``system_scope``: the worker has no principal, and dedup
must see every live listing regardless of who created it. That is the same
justification ``app/dedup.py`` uses for contact duplicate detection, and it is
narrow -- this module reads and writes inventory, never contacts.

The message is the unit of work and the unit of failure. A message either
completes (its listings are all merged or inserted, in one transaction) or is
left to retry, so a crash halfway through a six-listing message cannot leave
three orphans behind.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session as DbSession

from app.db import system_scope
from app.extraction import (
    ExtractedListing,
    RateLimited,
    ExtractionInput,
    Extractor,
    ExtractionUnavailable,
    MessageExtraction,
    REVIEW_THRESHOLD,
    confidence_score,
)
from app.listing_normalize import (
    CRORE,
    normalize_furnishing,
    normalize_listing_type,
    normalize_location,
    normalize_phone,
    normalize_price,
    normalize_property_type,
    parse_area,
    parse_bhk,
    parse_price,
)
from app.models import (
    INGEST_DUPLICATE,
    INGEST_EXTRACTED,
    INGEST_FAILED,
    INGEST_NOT_LISTING,
    INGEST_PENDING,
    INGEST_PROCESSING,
    MAX_EXTRACTION_ATTEMPTS,
    Property,
    PropertySource,
    WhatsAppGroup,
    WhatsAppMessage,
)
from app.property_dedup import (
    ListingFacts,
    apply_listing_to_property,
    build_dedupe_key,
    find_duplicate,
)

log = logging.getLogger("balaji.ingestion")

# Batch size per model call. Large enough to amortise the cached system prompt
# across many messages, small enough that one failure does not strand a big
# chunk of the backlog and that the response stays well inside max_tokens.
BATCH_SIZE = 8


# Words that make a message worth a model call even with no digits in it.
# Deliberately generous: the cost of keeping a non-listing is one entry in a
# batch, and the cost of dropping a listing is a flat the firm never sees.
_LISTING_WORDS = (
    "bhk", "rk", "flat", "apartment", "shop", "office", "villa", "plot",
    "rent", "lease", "sale", "sell", "resale", "buy", "available", "avl",
    "carpet", "sqft", "sq ft", "furnish", "deposit", "dep", "tenant",
    "possession", "society", "tower", "wing", "floor",
)

# Anchored at the start of a word, open at the end. The leading boundary is not
# optional: matching "lease" anywhere inside a message classifies "please share
# the photos" as inventory. The trailing end is left open on purpose, so
# "flats", "furnished" and "deposit" all match their stems.
_LISTING_RE = re.compile(r"\b(?:" + "|".join(_LISTING_WORDS) + r")", re.IGNORECASE)


def is_obvious_chatter(body: str) -> bool:
    """True for messages no model needs to see.

    Broker groups are mostly not inventory -- good mornings, festival wishes,
    "thanks bhai", a thumbs up. Every one of those used to cost a slot in a
    batch and a slice of the token allowance, which on a rate-limited tier is
    throughput taken directly from the messages that *are* listings.

    The test is deliberately timid, because the asymmetry is brutal: a dropped
    listing is a flat the firm never sees, while a kept non-listing costs
    almost nothing. So a message is skipped only when it is short, contains no
    digit anywhere -- no price, no size, no phone number, no floor -- and uses
    none of the vocabulary of inventory. "Good morning all 🙏" goes; anything
    that could conceivably be a flat stays.
    """
    text = body.strip().lower()
    if len(text) > 120:
        return False
    if any(character.isdigit() for character in text):
        return False
    return _LISTING_RE.search(text) is None


@dataclass
class IngestionStats:
    messages_processed: int = 0
    listings_found: int = 0
    properties_created: int = 0
    duplicates_merged: int = 0
    not_listings: int = 0
    failures: int = 0
    # Messages handed back untouched because the model allowance ran out.
    # Counted apart from failures: nothing went wrong with them.
    rate_limited: int = 0
    # How long the API asked us to wait, so the loop can sleep for about that
    # rather than spinning through the daily request allowance.
    retry_after: float = 0.0

    def as_dict(self) -> dict[str, int]:
        return {
            "messages_processed": self.messages_processed,
            "listings_found": self.listings_found,
            "properties_created": self.properties_created,
            "duplicates_merged": self.duplicates_merged,
            "not_listings": self.not_listings,
            "failures": self.failures,
            "rate_limited": self.rate_limited,
        }


def infer_listing_type(listing: ExtractedListing) -> str | None:
    """Settle on rent vs outright, since `properties.listing_type` is NOT NULL.

    Order of evidence: what the model said, then what the message's own words
    imply, then the price magnitude. The magnitude fallback is reliable in a
    way most heuristics are not -- no one rents a flat for ₹1.2 crore a month
    and no one sells one for ₹85,000.
    """
    # The model's answer, unless the listing contradicts itself.
    #
    # A pre-leased property is an investment for sale: the tenant and the rent
    # are what is being bought. Models read the rent schedule, the lock-in and
    # the escalation clause, and conclude "rent" -- while copying a title that
    # says "Pre-Leased Shop - Outright" and an asking price in crores. That is
    # not a judgement call to defer to, it is a flat contradiction, and the word
    # "pre-leased" settles it.
    #
    # Narrow on purpose: only this marker overrides the model. A generic "sale"
    # somewhere in a rental listing is ordinary noise and is left alone.
    if listing.listing_type == "rent":
        from_title = normalize_listing_type(listing.title)
        if from_title == "outright":
            return "outright"

    if listing.listing_type in ("rent", "outright"):
        return listing.listing_type

    from_text = normalize_listing_type(
        " ".join(filter(None, [listing.title, listing.price, listing.furnishing]))
    )
    if from_text:
        return from_text

    raw = parse_price(listing.price)
    if raw is None:
        return None
    # Explicit crore/lakh units in the raw text are a sale tell on their own.
    if raw >= 1_000_000:
        return "outright"
    if raw <= 500_000:
        return "rent"
    return None


def build_facts(listing: ExtractedListing) -> ListingFacts | None:
    """Normalize one extracted listing, or reject it as unusable.

    Rejection criteria are deliberately blunt: a listing with no locality and
    no building cannot be searched, matched or shown to a client, so storing it
    only adds noise to the inventory the firm is trying to unify.
    """
    listing_type = infer_listing_type(listing)
    if listing_type is None:
        return None

    location = normalize_location(listing.location)
    building = normalize_location(listing.building)
    if not location and not building:
        return None

    return ListingFacts(
        listing_type=listing_type,
        # location is NOT NULL in the schema; fall back to the building name
        # when the message named a tower but no locality.
        location=location or building or "",
        building=building,
        bhk=parse_bhk(listing.bhk),
        price=normalize_price(listing.price, listing_type),
        area_sqft=parse_area(listing.area),
        property_type=normalize_property_type(listing.property_type),
        furnishing=normalize_furnishing(listing.furnishing),
        contact_phone=normalize_phone(listing.contact_phone),
        contact_name=(listing.contact_name or "").strip() or None,
        title=(listing.title or "").strip() or None,
        confidence=confidence_score(listing.confidence),
        raw=listing.model_dump(),
    )


def _review_state(facts: ListingFacts) -> str:
    """Low-confidence extractions are published but flagged.

    Publishing beats withholding: an agent searching inventory would rather see
    a slightly-wrong listing they can sanity-check against the raw message than
    miss a real flat. The flag is what keeps that honest.
    """
    return "needs_review" if (facts.confidence or 0) < REVIEW_THRESHOLD else "auto_accepted"


def record_listing(
    db: DbSession,
    facts: ListingFacts,
    message: WhatsAppMessage,
    group: WhatsAppGroup | None,
) -> tuple[Property, bool]:
    """Insert the listing, or merge it into the property it duplicates.

    Returns ``(property, created)``. Both paths write a ``property_sources``
    row, which is what makes "this flat was posted by 4 brokers in 3 groups"
    answerable later.
    """
    match = find_duplicate(db, facts)

    if match.is_duplicate and match.property_id is not None:
        with system_scope():
            prop = db.get(Property, match.property_id)
        if prop is not None:
            filled = apply_listing_to_property(prop, facts)
            _attach_source(
                db,
                prop,
                message,
                group,
                facts,
                relation="duplicate",
                score=match.score,
            )
            log.info(
                "merged listing into property %s (score=%.2f, %s), filled=%s",
                prop.id,
                match.score,
                match.reason,
                filled or "nothing",
            )
            return prop, False

    now = datetime.now(timezone.utc)
    prop = Property(
        title=facts.title,
        location=facts.location,
        building=facts.building,
        property_type=facts.property_type,
        listing_type=facts.listing_type,
        price=facts.price,
        status="available",
        source="whatsapp_group",
        raw_message=message.body,
        source_group=group.name if group else None,
        bhk=facts.bhk,
        area_sqft=facts.area_sqft,
        furnishing=facts.furnishing,
        contact_name=facts.contact_name,
        contact_phone=facts.contact_phone,
        dedupe_key=build_dedupe_key(facts),
        extraction_confidence=facts.confidence,
        review_state=_review_state(facts),
        last_seen_at=now,
        # posted_by_agent_id stays NULL: nobody at the firm listed this. That
        # distinction matters for "who showed what to whom" attribution.
    )
    db.add(prop)
    db.flush()  # need prop.id for the source row

    _attach_source(
        db, prop, message, group, facts, relation="origin", score=match.score
    )
    return prop, True


def _attach_source(
    db: DbSession,
    prop: Property,
    message: WhatsAppMessage,
    group: WhatsAppGroup | None,
    facts: ListingFacts,
    *,
    relation: str,
    score: float | None,
) -> None:
    """Record one sighting, idempotently.

    Re-running the extractor over an already-processed message (after a prompt
    fix, say) must not inflate the repost count, so an existing
    (property, message) pair is left alone.
    """
    with system_scope():
        existing = db.execute(
            select(PropertySource.id).where(
                PropertySource.property_id == prop.id,
                PropertySource.message_id == message.id,
            )
        ).first()
    if existing:
        return

    # The same check against sightings this transaction has not written yet.
    #
    # The session is `autoflush=False`, so the SELECT above sees only what is
    # committed -- a sighting added moments ago, for a *different* flat in this
    # same message, is still sitting in `db.new` and is invisible to it. One
    # message routinely carries several flats, and when two of them resolve to
    # one property (two units of the same configuration in one tower, a repost
    # of a building's whole availability list) the second add used to collide
    # with the first at commit.
    #
    # It failed loudly and expensively: uq_property_source aborts the flush, so
    # the message failed as a whole and every listing in it was lost, including
    # the ones that had nothing wrong with them.
    for pending in db.new:
        if (
            isinstance(pending, PropertySource)
            and pending.property_id == prop.id
            and pending.message_id == message.id
        ):
            return

    db.add(
        PropertySource(
            property_id=prop.id,
            message_id=message.id,
            group_id=message.group_id,
            group_name=group.name if group else None,
            posted_by_name=facts.contact_name or message.sender_name,
            posted_by_phone=facts.contact_phone
            or normalize_phone(message.sender_jid),
            raw_message=message.body,
            relation=relation,
            match_score=score,
        )
    )


def process_message(
    db: DbSession,
    message: WhatsAppMessage,
    result: MessageExtraction,
    group: WhatsAppGroup | None,
    stats: IngestionStats,
) -> None:
    """Apply one extraction result to one message, in the caller's transaction."""
    message.extraction = result.model_dump()
    message.processed_at = datetime.now(timezone.utc)
    message.claimed_at = None
    message.error = None

    if not result.is_listing or not result.listings:
        message.status = INGEST_NOT_LISTING
        message.listings_found = 0
        message.listings_new = 0
        stats.not_listings += 1
        return

    found = 0
    created = 0
    for listing in result.listings:
        facts = build_facts(listing)
        if facts is None:
            log.info(
                "message %s: dropped an unusable listing (no locality or no type)",
                message.id,
            )
            continue
        found += 1
        _, was_created = record_listing(db, facts, message, group)
        if was_created:
            created += 1
            stats.properties_created += 1
        else:
            stats.duplicates_merged += 1

    message.listings_found = found
    message.listings_new = created
    stats.listings_found += found

    if found == 0:
        # The model called it a listing but nothing survived normalization.
        message.status = INGEST_NOT_LISTING
        stats.not_listings += 1
    elif created == 0:
        message.status = INGEST_DUPLICATE
    else:
        message.status = INGEST_EXTRACTED

    if group is not None and created:
        group.listing_count = (group.listing_count or 0) + created


def claim_pending(db: DbSession, limit: int) -> list[WhatsAppMessage]:
    """Atomically claim a batch of pending messages.

    ``SKIP LOCKED`` so two workers can run side by side without both grabbing
    the same rows -- the owner is likely to run one worker, but a backlog after
    an outage is exactly when someone starts a second.
    """
    with system_scope():
        rows = (
            db.execute(
                select(WhatsAppMessage)
                .where(WhatsAppMessage.status == INGEST_PENDING)
                .where(WhatsAppMessage.attempts < MAX_EXTRACTION_ATTEMPTS)
                .order_by(WhatsAppMessage.received_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        claimed = list(rows)
        now = datetime.now(timezone.utc)
        for message in claimed:
            message.status = INGEST_PROCESSING
            message.attempts = (message.attempts or 0) + 1
            message.claimed_at = now
    db.commit()
    return claimed


# How long a claim may sit before it is assumed dead.
#
# Generous, because a slow batch is still a live one: on a free model tier a
# batch that gets rate-limited retries with a long backoff, and reclaiming it
# mid-flight would double the work and could double-create inventory.
STALLED_CLAIM_AFTER = timedelta(minutes=15)


def reclaim_stalled(db: DbSession, older_than: timedelta = STALLED_CLAIM_AFTER) -> int:
    """Return claims whose worker never came back to the queue.

    Nothing did this, and the gap was invisible in the worst way: a claimed row
    is `processing`, `claim_pending` only looks at `pending`, and the owner's
    "retry failed" only looks at `failed`. A message whose worker died mid-batch
    was reachable by neither and sat on "Extracting" for ever.

    That is not an edge case on the free plan, where the extraction loop runs
    inside an API that suspends after about fifteen minutes without traffic --
    it dies mid-batch most days.

    The attempt taken by the claim is given back. `attempts` exists to stop one
    malformed message being re-sent to the model for ever, and a host suspending
    is not the message's fault; charging it would fail perfectly good messages
    after three deploys. The timeout is what bounds this instead — a message
    that genuinely kills its worker can only cost one attempt per fifteen
    minutes, which is slow enough to notice and cheap enough to survive.
    """
    cutoff = datetime.now(timezone.utc) - older_than
    with system_scope():
        ids = [
            row[0]
            for row in db.execute(
                select(WhatsAppMessage.id)
                .where(WhatsAppMessage.status == INGEST_PROCESSING)
                .where(
                    or_(
                        WhatsAppMessage.claimed_at.is_(None),
                        WhatsAppMessage.claimed_at < cutoff,
                    )
                )
            )
        ]
        if not ids:
            return 0
        db.execute(
            update(WhatsAppMessage)
            .where(WhatsAppMessage.id.in_(ids))
            .values(
                status=INGEST_PENDING,
                claimed_at=None,
                attempts=func.greatest(WhatsAppMessage.attempts - 1, 0),
                error="Requeued: the extractor stopped before finishing this batch.",
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
    log.warning("reclaimed %d message(s) stalled in extraction", len(ids))
    return len(ids)


def _groups_for(db: DbSession, messages: list[WhatsAppMessage]) -> dict[int, WhatsAppGroup]:
    ids = {m.group_id for m in messages}
    if not ids:
        return {}
    with system_scope():
        rows = db.execute(
            select(WhatsAppGroup).where(WhatsAppGroup.id.in_(ids))
        ).scalars().all()
    return {g.id: g for g in rows}


def run_batch(
    db: DbSession, extractor: Extractor, *, limit: int = BATCH_SIZE
) -> IngestionStats:
    """Claim, extract and apply one batch. Returns what happened."""
    stats = IngestionStats()
    claimed = claim_pending(db, limit)
    if not claimed:
        return stats

    # Settle the obvious ones here rather than paying a model call for them.
    # In these groups most traffic is not inventory, and on a rate-limited tier
    # every greeting in a batch is throughput taken from a real listing.
    messages = []
    for message in claimed:
        if is_obvious_chatter(message.body):
            message.status = INGEST_NOT_LISTING
            message.claimed_at = None
            message.processed_at = datetime.now(timezone.utc)
            message.error = None
            stats.not_listings += 1
            stats.messages_processed += 1
        else:
            messages.append(message)

    if not messages:
        db.commit()
        return stats

    groups = _groups_for(db, messages)
    items = [
        ExtractionInput(
            ref=str(m.id),
            body=m.body,
            group_name=groups[m.group_id].name if m.group_id in groups else None,
            group_note=groups[m.group_id].note if m.group_id in groups else None,
            sender_name=m.sender_name,
        )
        for m in messages
    ]

    try:
        results = extractor.extract(items)
    except RateLimited as exc:
        # Not the batch's fault, so it must not cost the batch anything. These
        # messages are word-for-word fine and will extract on the next pass;
        # charging them an attempt would fail a perfectly good backlog after
        # three busy minutes, exactly as charging one for the host suspending
        # mid-batch would.
        log.warning("all models rate limited: %s", exc)
        _release(db, messages, str(exc), charge_attempt=False)
        stats.rate_limited += len(messages)
        stats.retry_after = max(stats.retry_after, exc.retry_after)
        return stats
    except Exception as exc:
        # The whole batch failed (network, rate limit, refusal). Release the
        # claim so it retries; `attempts` was already incremented, so a
        # permanently poisonous batch stops after MAX_EXTRACTION_ATTEMPTS.
        log.warning("extraction batch failed: %s", exc)
        _release(db, messages, str(exc))
        stats.failures += len(messages)
        return stats

    by_id = {str(m.id): m for m in messages}
    for result in results:
        message = by_id.get(result.message_ref)
        if message is None:
            continue
        # Snapshot the identifiers now: the rollback in the failure path
        # expires the ORM object, and reading its attributes afterwards would
        # trigger a lazy refresh SELECT that the scoping guard rejects.
        message_id, attempts = message.id, message.attempts or 0
        try:
            process_message(db, message, result, groups.get(message.group_id), stats)
            stats.messages_processed += 1
        except Exception as exc:  # one bad message must not sink the batch
            log.exception("failed to apply extraction for message %s", message_id)
            db.rollback()
            _mark_failed(db, message_id, attempts, str(exc))
            stats.failures += 1

    _bump_group_counters(db, messages, groups)
    db.commit()
    return stats


def _release(
    db: DbSession,
    messages: list[WhatsAppMessage],
    error: str,
    *,
    charge_attempt: bool = True,
) -> None:
    """Return claimed messages to the queue, or fail them if out of attempts.

    ``charge_attempt=False`` hands back the attempt the claim took. It is for
    failures that belong to the infrastructure rather than the message -- a
    rate limit, a worker killed mid-batch -- where counting them would retire
    messages that were never the problem.

    ``synchronize_session=False`` throughout: the default strategy issues a
    SELECT to reconcile in-session objects, and that SELECT does not carry the
    scoping marker, so the guard in ``app/db.py`` rejects it. Nothing here
    re-reads the ORM objects afterwards, so there is no state to synchronize.
    """
    # Read the ids *before* rolling back. A rollback expires every loaded ORM
    # object, so touching `m.id` afterwards issues a lazy refresh SELECT --
    # which carries no scope marker and is rejected by the guard in app/db.py.
    ids = [m.id for m in messages]
    db.rollback()
    with system_scope():
        db.execute(
            update(WhatsAppMessage)
            .where(WhatsAppMessage.id.in_(ids))
            .values(
                status=INGEST_PENDING,
                claimed_at=None,
                error=error[:1000],
                **(
                    {}
                    if charge_attempt
                    else {"attempts": func.greatest(WhatsAppMessage.attempts - 1, 0)}
                ),
            )
            .execution_options(synchronize_session=False)
        )
        if charge_attempt:
            # Second pass rather than a CASE: a message only exhausts its
            # retries once `attempts` has already been incremented by the claim.
            db.execute(
                update(WhatsAppMessage)
                .where(WhatsAppMessage.id.in_(ids))
                .where(WhatsAppMessage.attempts >= MAX_EXTRACTION_ATTEMPTS)
                .values(status=INGEST_FAILED)
                .execution_options(synchronize_session=False)
            )
        db.commit()


def _mark_failed(
    db: DbSession, message_id: int, attempts: int, error: str
) -> None:
    """Takes primitives, not an ORM object: the caller has already rolled back,
    which expires every loaded instance."""
    with system_scope():
        db.execute(
            update(WhatsAppMessage)
            .where(WhatsAppMessage.id == message_id)
            .values(
                status=(
                    INGEST_FAILED
                    if attempts >= MAX_EXTRACTION_ATTEMPTS
                    else INGEST_PENDING
                ),
                claimed_at=None,
                error=error[:1000],
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()


def _bump_group_counters(
    db: DbSession,
    messages: list[WhatsAppMessage],
    groups: dict[int, WhatsAppGroup],
) -> None:
    latest: dict[int, datetime] = {}
    for message in messages:
        stamp = message.sent_at or message.received_at
        if message.group_id and stamp:
            current = latest.get(message.group_id)
            if current is None or stamp > current:
                latest[message.group_id] = stamp
    for group_id, stamp in latest.items():
        group = groups.get(group_id)
        if group is not None and (
            group.last_message_at is None or stamp > group.last_message_at
        ):
            group.last_message_at = stamp


def pending_count(db: DbSession) -> int:
    with system_scope():
        return db.execute(
            select(func.count())
            .select_from(WhatsAppMessage)
            .where(WhatsAppMessage.status == INGEST_PENDING)
        ).scalar_one()
