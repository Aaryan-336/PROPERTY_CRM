"""Normalization for extracted WhatsApp listings.

The LLM reads the message; this module makes its output *comparable*. The split
matters: the model is good at "what is this text saying" and bad at being
consistent to the rupee, so it is asked for values in a small number of stated
units and everything downstream -- dedup especially -- works on canonical
numbers produced here.

Indian real-estate shorthand is the whole problem. All of these appear in the
same group on the same day and mean the same thing:

    1.2 Cr    1,20,00,000    120 lakh    ₹1.2Cr    1.2 crores    Rs 1.2 cr

and for rent:

    85k    85,000/-    85000 pm    Rs.85000 per month    0.85 lakh

Everything here is deterministic and unit-tested, so a parsing bug is found by
running the tests rather than by an owner spotting a ₹85,000 flat listed at
₹8.5 crore.
"""

from __future__ import annotations

import re
import unicodedata

# Indian numbering. 1 lakh = 100_000; 1 crore = 100 lakh = 10_000_000.
LAKH = 100_000
CRORE = 10_000_000

# Rent above this is almost certainly a sale price the poster forgot to label,
# and a sale below it is almost certainly a monthly rent. Used only to correct
# an obviously mislabelled listing_type, never to reject one.
RENT_SANITY_CEILING = 2_000_000     # ₹20L/month
SALE_SANITY_FLOOR = 500_000         # ₹5L outright

_MULTIPLIERS: tuple[tuple[str, int], ...] = (
    # Longest first so "crore" is matched before "cr", and "lakhs" before "l".
    ("crores", CRORE),
    ("crore", CRORE),
    ("cror", CRORE),
    ("cr", CRORE),
    ("lakhs", LAKH),
    ("lakh", LAKH),
    ("lacs", LAKH),
    ("lac", LAKH),
    ("lak", LAKH),
    ("l", LAKH),
    ("k", 1_000),
)

_CURRENCY_NOISE = re.compile(
    r"(?:₹|rs\.?|inr|rupees?|/-|per\s*month|p\.?m\.?|monthly|onwards|approx\.?|"
    r"negotiable|neg\.?|only|nett?|all\s*incl(?:usive)?)",
    re.IGNORECASE,
)

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

FURNISHING_MAP = {
    "furnished": "furnished",
    "fully furnished": "furnished",
    "full furnished": "furnished",
    "ff": "furnished",
    "semi furnished": "semi_furnished",
    "semi-furnished": "semi_furnished",
    "semifurnished": "semi_furnished",
    "sf": "semi_furnished",
    "unfurnished": "unfurnished",
    "un furnished": "unfurnished",
    "bare shell": "unfurnished",
    "bareshell": "unfurnished",
    "uf": "unfurnished",
}

PROPERTY_TYPE_MAP = {
    "apartment": "apartment",
    "flat": "apartment",
    "villa": "villa",
    "bungalow": "villa",
    "row house": "villa",
    "rowhouse": "villa",
    "plot": "plot",
    "land": "plot",
    "commercial": "commercial",
    "office": "commercial",
    "shop": "commercial",
    "showroom": "commercial",
    "warehouse": "commercial",
    "godown": "commercial",
}


def _clean(text: str) -> str:
    """Strip currency noise and normalize unicode so parsing sees plain ASCII."""
    text = unicodedata.normalize("NFKC", text)
    text = _CURRENCY_NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _to_float(raw: str) -> float | None:
    """Parse a number that may carry Indian or Western digit grouping.

    ``1,20,00,000`` (Indian) and ``1,200,000`` (Western) both mean a plain
    integer once separators are dropped. A comma is only a decimal point in
    locales that do not appear in this data, so commas are always separators
    here; a single trailing ``.`` group is a genuine decimal.
    """
    raw = raw.strip()
    if not raw:
        return None
    if "." in raw:
        head, _, tail = raw.rpartition(".")
        # "1.2" -> decimal. "1.20.000" -> the dots are separators.
        if head and tail and len(tail) <= 2 and head.count(".") == 0:
            head = head.replace(",", "")
            try:
                return float(f"{head}.{tail}")
            except ValueError:
                return None
        raw = raw.replace(".", "")
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_price_parts(
    text: str | float | int | None,
) -> tuple[float, bool] | None:
    """Return ``(value, had_explicit_unit)`` without rounding.

    Split out from ``parse_price`` because the magnitude repair in
    ``normalize_price`` needs two things the rounded integer has thrown away:
    the fractional part, and whether the poster actually named a unit.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        value = float(text)
        # A number that arrived already typed carries no unit string, but it
        # also was not shorthand -- treat it as an absolute figure.
        return (value, True) if value > 0 else None

    cleaned = _clean(str(text))
    if not cleaned:
        return None

    match = _NUMBER.search(cleaned)
    if not match:
        return None
    value = _to_float(match.group())
    if value is None or value <= 0:
        return None

    # Look at what follows the number for a unit word. Anchoring to the text
    # *after* the number avoids "3 BHK 85k" picking up a stray letter.
    tail = cleaned[match.end() :].lstrip(" .-")
    for token, multiplier in _MULTIPLIERS:
        if tail.startswith(token):
            # Guard against "l" matching the "l" of a following word and "k"
            # matching "kitchen": require the unit to end the token.
            rest = tail[len(token) :]
            if rest[:1].isalpha():
                continue
            return (value * multiplier, True)

    # Digit grouping is itself a unit signal: nobody writes "1,20,00,000" and
    # means anything other than that exact number of rupees.
    grouped = "," in match.group()
    return (value, grouped)


def _is_plausible(value: float, listing_type: str | None) -> bool:
    """Could this number already be an absolute rupee figure?

    Guards the shorthand inference in :func:`normalize_price`: a bare ``85000``
    for rent is a real monthly rent and must be left alone, while a bare ``85``
    cannot be and has to be expanded.
    """
    if listing_type == "rent":
        return 3_000 <= value <= RENT_SANITY_CEILING
    if listing_type == "outright":
        return SALE_SANITY_FLOOR <= value <= 100 * CRORE
    # Unknown type: anything above a lakh is plausible as-is either way.
    return value >= LAKH


def parse_price(text: str | float | int | None) -> int | None:
    """Return a price in whole rupees, or None if nothing parseable is present.

    Takes the text at face value -- ``"45"`` is forty-five rupees here. Use
    :func:`normalize_price` when the value came off a listing, where a bare
    ``45`` means forty-five lakh.

    >>> parse_price("1.2 Cr")
    12000000
    >>> parse_price("85k")
    85000
    >>> parse_price("1,20,00,000")
    12000000
    >>> parse_price("45 lakh")
    4500000
    """
    parts = _parse_price_parts(text)
    if parts is None:
        return None
    return int(round(parts[0]))


def normalize_price(
    price: str | float | int | None, listing_type: str | None
) -> int | None:
    """Parse a listing price, resolving shorthand and repairing bad magnitudes.

    Two distinct problems, in order:

    1. **Unitless shorthand.** Posters drop the unit constantly, and what they
       meant is recoverable from whether they wrote a fraction. ``"1.2"`` rent
       is 1.2 *lakh*; ``"85"`` rent is 85 *thousand*. Nobody writes "1.2" to
       mean one rupee twenty, and nobody writes "85" to mean 85 lakh a month.
       So: a fractional value is lakh (rent) or crore (sale); a whole number is
       thousand (rent) or lakh (sale).

    2. **Mislabelled magnitude.** A "rent" of ₹1.2 crore is a unit that got
       lost between the poster's head and the message. Rescaling is safe
       because monthly rents and sale prices do not overlap in any real market.
       Rescaling the *listing_type* would not be safe, so this never does that.
    """
    parts = _parse_price_parts(price)
    if parts is None:
        return None
    value, had_unit = parts

    if not had_unit and not _is_plausible(value, listing_type):
        # Only reached when the bare number is too small to be a real figure,
        # so it must be shorthand. "85000" for rent is left alone; "85" is not.
        has_fraction = abs(value - round(value)) > 1e-9
        if listing_type == "rent":
            value *= LAKH if has_fraction else 1_000
        elif listing_type == "outright":
            value *= CRORE if has_fraction else LAKH
        elif has_fraction:
            # Unknown listing type: a fraction is still certainly shorthand,
            # and lakh is the safer of the two guesses.
            value *= LAKH

    result = int(round(value))
    if result <= 0:
        return None

    if listing_type == "rent":
        while result > RENT_SANITY_CEILING:
            result //= 100
            if result < 1_000:
                return None
    elif listing_type == "outright":
        while result < SALE_SANITY_FLOOR:
            result *= 100
            if result > 100 * CRORE:
                return None
    return result


def parse_bhk(text: str | int | None) -> int | None:
    """Extract the bedroom count.

    Handles "3BHK", "3 bhk", "3 bed", "2.5 BHK" (rounds down -- the half is a
    study, and treating it as a 3BHK would merge two different flats), and the
    studio/1RK convention where the answer is 0 rather than missing.
    """
    if text is None:
        return None
    if isinstance(text, int):
        return text if 0 <= text <= 20 else None

    lowered = _clean(str(text))
    if not lowered:
        return None
    if "studio" in lowered or re.search(r"\b1\s*rk\b", lowered):
        return 0

    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:bhk|bed|bd|b\.h\.k)", lowered)
    if not match:
        # A bare integer is only a BHK if that is all the field contains --
        # otherwise "500 sqft" would read as a 500BHK.
        if re.fullmatch(r"\d{1,2}", lowered):
            value = int(lowered)
            return value if 0 <= value <= 20 else None
        return None

    value = float(match.group(1))
    return int(value) if 0 <= value <= 20 else None


def parse_area(text: str | int | float | None) -> int | None:
    """Return area in square feet.

    Converts square yards and square metres, which appear in plot listings and
    in messages from posters used to those units.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(round(text)) if text > 0 else None

    lowered = _clean(str(text))
    match = _NUMBER.search(lowered)
    if not match:
        return None
    value = _to_float(match.group())
    if value is None or value <= 0:
        return None

    tail = lowered[match.end() :]
    if re.search(r"\b(?:sq\.?\s*yd|sqyd|square\s*yard|gaj)", tail):
        value *= 9.0
    elif re.search(r"\b(?:sq\.?\s*m|sqm|square\s*met)", tail):
        value *= 10.7639
    elif re.search(r"\b(?:acre)", tail):
        value *= 43560.0

    result = int(round(value))
    # Anything outside this range is a misparse (a price that reached the area
    # field, usually), not a real flat.
    return result if 50 <= result <= 5_000_000 else None


def normalize_furnishing(text: str | None) -> str | None:
    if not text:
        return None
    lowered = _clean(str(text))
    if lowered in FURNISHING_MAP:
        return FURNISHING_MAP[lowered]
    # Order matters: "semi furnished" contains "furnished".
    if "semi" in lowered:
        return "semi_furnished"
    if "unfurnish" in lowered or "bare" in lowered:
        return "unfurnished"
    if "furnish" in lowered:
        return "furnished"
    return None


def normalize_property_type(text: str | None) -> str | None:
    """Map free text onto the four types in DATA_MODEL.md."""
    if not text:
        return None
    lowered = _clean(str(text))
    if lowered in PROPERTY_TYPE_MAP:
        return PROPERTY_TYPE_MAP[lowered]
    for token, mapped in PROPERTY_TYPE_MAP.items():
        if token in lowered:
            return mapped
    return None


def normalize_listing_type(text: str | None) -> str | None:
    """Map free text onto rent/outright (DATA_MODEL.md's two listing types)."""
    if not text:
        return None
    lowered = _clean(str(text))
    if any(
        token in lowered
        for token in ("rent", "lease", "letting", "to let", "rental")
    ):
        return "rent"
    if any(
        token in lowered
        for token in ("sale", "sell", "outright", "buy", "resale", "purchase")
    ):
        return "outright"
    return None


_PHONE_NOISE = re.compile(r"[^\d+]")


def normalize_phone(text: str | None) -> str | None:
    """Reduce an Indian mobile number to its last 10 digits.

    Posters write +91, 0091, a leading 0, or nothing at all, and the same
    broker's number has to compare equal across all of them.
    """
    if not text:
        return None
    digits = _PHONE_NOISE.sub("", str(text)).lstrip("+")
    if not digits:
        return None
    if len(digits) >= 10:
        return digits[-10:]
    return None


_LOCATION_NOISE = re.compile(
    r"\b(?:near|opp\.?|opposite|behind|beside|next\s+to|above|below)\b",
    re.IGNORECASE,
)


def normalize_location(text: str | None) -> str | None:
    """Tidy a locality string without trying to geocode it.

    Deliberately conservative: it title-cases and strips landmark prefixes so
    "near andheri west" and "Andheri West" land in the same bucket, but it does
    not attempt to resolve aliases ("Bandra" vs "BKC"), which needs a gazetteer
    the firm does not have yet.
    """
    if not text:
        return None
    cleaned = _LOCATION_NOISE.sub(" ", str(text))
    cleaned = re.sub(r"[,\-–—]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    if not cleaned:
        return None
    return cleaned.title()


def canonical_token(text: str | None) -> str:
    """Lowercase alphanumeric-only form, for keys and fuzzy comparison.

    "Lodha Amara, Tower 3" and "lodha amara tower-3" produce the same token,
    which is what makes them dedup candidates.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text)).lower()
    return re.sub(r"[^a-z0-9]+", "", normalized)
