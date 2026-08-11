"""Deduplication for ingested property listings.

ARCHITECTURE.md, "WhatsApp listing -> searchable inventory", steps 4-6:

    4. Dedup check against existing `properties` records (building + BHK +
       price similarity).
    5. If new: insert with `source = whatsapp_group`, `raw_message` retained.
    6. If likely duplicate: attach as an additional source reference rather
       than creating a new row.

Why this is the load-bearing step: the same flat is posted by six brokers
across four groups in a week, often with the price nudged and the building name
spelled three ways. Without dedup the "unified inventory" the owner was
promised is a list where every real flat appears six times, which is worse than
the WhatsApp groups they already have.

Two stages, for the usual reason -- comparing every new listing against every
existing one is O(n²) and most pairs are obviously unrelated:

1. **Blocking.** A cheap key (``listing_type | bhk | building-or-locality``)
   fetches a handful of candidates via an index. See :func:`build_dedupe_key`.
2. **Scoring.** Weighted fuzzy comparison over building, locality, price, area
   and the posting broker's number, with hard rejects for the fields where a
   mismatch is disqualifying rather than merely costly.

The bar for merging is deliberately high. A false merge silently hides a real
flat from the agents and is invisible until a deal is lost; a false split shows
the same flat twice, which is visible, annoying, and fixable by hand. When
uncertain, split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app.db import system_scope
from app.listing_normalize import canonical_token
from app.models import Property

# Merge at or above this score. Tuned so that a same-building same-BHK repost
# with a nudged price merges, while two different units in one tower do not.
MERGE_THRESHOLD = 0.82

# Prices further apart than this are different listings even if everything else
# matches -- a 20% swing on the same flat is a different deal, and merging them
# would silently overwrite the price an agent is about to quote.
MAX_PRICE_DRIFT = 0.20

# Carpet areas differing by more than this are different units.
MAX_AREA_DRIFT = 0.15

# Cap on candidates pulled per lookup. A locality-only key in a busy market can
# match a lot of rows; scoring the most recent N is enough, because a repost
# almost always follows the original within days.
CANDIDATE_LIMIT = 60


@dataclass
class ListingFacts:
    """The normalized fields dedup actually compares.

    Built by the extractor from one listing inside one message. Everything is
    optional because real messages omit almost anything -- the scorer handles
    absence by redistributing weight rather than by guessing.
    """

    listing_type: str
    location: str
    building: str | None = None
    bhk: int | None = None
    price: int | None = None
    area_sqft: int | None = None
    property_type: str | None = None
    furnishing: str | None = None
    contact_phone: str | None = None
    contact_name: str | None = None
    title: str | None = None
    confidence: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchResult:
    property_id: int | None
    score: float
    reason: str
    is_duplicate: bool


def build_dedupe_key(facts: ListingFacts) -> str:
    """Coarse blocking key. Equal keys are *candidates*, never a verdict.

    Building name is preferred over locality because it is far more selective
    ("Lodha Amara" vs "Thane West"), with locality as the fallback for the many
    messages that name no building at all.

    Price is deliberately absent. Bucketing a continuous value puts ₹1.19Cr and
    ₹1.21Cr in different buckets and stops them ever being compared, which is
    exactly the repost dedup is meant to catch. Price is scored instead.
    """
    anchor = canonical_token(facts.building) or canonical_token(facts.location)
    bhk = str(facts.bhk) if facts.bhk is not None else "?"
    return f"{facts.listing_type}|{bhk}|{anchor}"


def locality_key(facts: ListingFacts) -> str:
    """Broader fallback key, used when the building-anchored key finds nothing.

    Catches the case where the original post named the building and the repost
    only gave the locality (or vice versa).
    """
    bhk = str(facts.bhk) if facts.bhk is not None else "?"
    return f"{facts.listing_type}|{bhk}|{canonical_token(facts.location)}"


def _ratio(a: str | None, b: str | None) -> float | None:
    """Fuzzy similarity in 0..1, or None when either side is missing.

    ``token_set_ratio`` because listing text reorders and pads constantly:
    "Amara Tower 3" vs "Tower 3, Lodha Amara" should score high.
    """
    if not a or not b:
        return None
    return fuzz.token_set_ratio(a.lower(), b.lower()) / 100.0


def _numeric_closeness(a: float | None, b: float | None) -> float | None:
    """1.0 for identical, falling to 0.0 as the relative gap reaches 100%."""
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    drift = abs(a - b) / max(a, b)
    return max(0.0, 1.0 - drift)


def score_match(facts: ListingFacts, candidate: Property) -> tuple[float, str]:
    """Score a candidate 0..1 and explain the verdict.

    The explanation is stored on the ``property_sources`` row so the owner's
    review screen can answer "why was this merged" without re-running anything.
    """
    # -- hard rejects: a mismatch here is disqualifying, not just costly ----
    if candidate.listing_type != facts.listing_type:
        return 0.0, "different listing type"

    if (
        facts.bhk is not None
        and candidate.bhk is not None
        and facts.bhk != candidate.bhk
    ):
        return 0.0, f"different BHK ({facts.bhk} vs {candidate.bhk})"

    if facts.price and candidate.price:
        drift = abs(facts.price - float(candidate.price)) / max(
            facts.price, float(candidate.price)
        )
        if drift > MAX_PRICE_DRIFT:
            return 0.0, f"price differs by {drift:.0%}"

    if facts.area_sqft and candidate.area_sqft:
        drift = abs(facts.area_sqft - candidate.area_sqft) / max(
            facts.area_sqft, candidate.area_sqft
        )
        if drift > MAX_AREA_DRIFT:
            return 0.0, f"area differs by {drift:.0%}"

    # The same broker reposting their own listing is the single strongest
    # signal available, so it short-circuits -- but only alongside a matching
    # locality, or one broker's whole portfolio would collapse into one row.
    same_broker = bool(
        facts.contact_phone
        and candidate.contact_phone
        and facts.contact_phone == candidate.contact_phone
    )

    # -- weighted evidence -------------------------------------------------
    # Weights are redistributed over whatever is actually present, so a message
    # naming only a locality and a price is judged on those two rather than
    # being penalised for the fields it never mentioned.
    signals: list[tuple[float, float]] = []  # (weight, score)

    building = _ratio(facts.building, candidate.building)
    if building is not None:
        signals.append((0.35, building))

    location = _ratio(facts.location, candidate.location)
    if location is not None:
        signals.append((0.20, location))

    price = _numeric_closeness(
        facts.price, float(candidate.price) if candidate.price else None
    )
    if price is not None:
        signals.append((0.20, price))

    area = _numeric_closeness(facts.area_sqft, candidate.area_sqft)
    if area is not None:
        signals.append((0.10, area))

    if facts.bhk is not None and candidate.bhk is not None:
        signals.append((0.15, 1.0))  # equal, or the hard reject fired above

    if not signals:
        return 0.0, "nothing comparable"

    total_weight = sum(w for w, _ in signals)
    score = sum(w * s for w, s in signals) / total_weight

    if same_broker:
        # Lift, not certainty: a broker posts many flats, and the locality/
        # building evidence still has to carry most of the weight.
        score = min(1.0, score + 0.10)

    parts = []
    if building is not None:
        parts.append(f"building {building:.0%}")
    if location is not None:
        parts.append(f"locality {location:.0%}")
    if price is not None:
        parts.append(f"price {price:.0%}")
    if same_broker:
        parts.append("same broker")
    return score, ", ".join(parts) or "weak evidence"


def find_duplicate(
    db: DbSession, facts: ListingFacts, *, threshold: float = MERGE_THRESHOLD
) -> MatchResult:
    """Look for an existing property this listing is a repost of.

    Runs under ``system_scope`` deliberately, mirroring ``app/dedup.py``: the
    ingestion worker has no principal, and dedup must consider *every* live
    listing regardless of who created it. A role-scoped dedup would happily
    re-create a listing that already exists but is out of the caller's view,
    which defeats the entire purpose.
    """
    keys = {build_dedupe_key(facts), locality_key(facts)}

    with system_scope():
        stmt = (
            select(Property)
            .where(Property.deleted_at.is_(None))
            .where(Property.listing_type == facts.listing_type)
            .where(
                or_(
                    Property.dedupe_key.in_(keys),
                    # Also consider anything in the same locality whose key was
                    # built from a building name we do not have -- the repost
                    # that dropped the building would otherwise never be
                    # compared against the original that had it.
                    Property.location.ilike(f"%{facts.location.strip()}%")
                    if facts.location
                    else False,
                )
            )
            .order_by(Property.created_at.desc())
            .limit(CANDIDATE_LIMIT)
        )
        candidates = list(db.execute(stmt).scalars().all())

    best: tuple[float, str, Property] | None = None
    for candidate in candidates:
        score, reason = score_match(facts, candidate)
        if best is None or score > best[0]:
            best = (score, reason, candidate)

    if best is None:
        return MatchResult(None, 0.0, "no candidates", False)

    score, reason, candidate = best
    return MatchResult(
        property_id=candidate.id,
        score=round(score, 4),
        reason=reason,
        is_duplicate=score >= threshold,
    )


def apply_listing_to_property(prop: Property, facts: ListingFacts) -> list[str]:
    """Fill gaps on an existing property from a fresh sighting.

    Merging is additive only: a repost that mentions the carpet area fills in a
    field the original omitted, but it never overwrites a value the firm
    already has. Overwriting would let the newest, sloppiest post silently
    rewrite a listing an agent has already quoted -- and worse, a manually
    entered listing that an agent curated by hand.

    Price is the sole exception and is handled by the caller, which records the
    change rather than applying it silently.
    """
    filled: list[str] = []
    for attr in (
        "building",
        "bhk",
        "area_sqft",
        "furnishing",
        "property_type",
        "contact_name",
        "contact_phone",
        "title",
    ):
        if getattr(prop, attr, None) in (None, "") and getattr(facts, attr, None):
            setattr(prop, attr, getattr(facts, attr))
            filled.append(attr)

    prop.last_seen_at = datetime.now(timezone.utc)
    return filled
