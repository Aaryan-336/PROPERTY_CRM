"""Reel-based campaign suggestions, and creating a campaign from one.

The suggestions are deliberately rule-based rather than model-generated: every
number on the screen has to be explainable to the person about to spend money
on it. A reel is scored on how far it travelled (reach) and how hard it held
people (shares and saves weigh more than likes, because they are the actions
that predict someone wanting the thing), then matched against what the CRM
knows -- which areas leads are asking for and where inventory exists -- so the
reasons read like the owner's own business, not generic ad advice.

Creation always lands PAUSED. Nothing here can spend money by itself.
"""

from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import system_scope
from app.meta_ads import GraphAds, MetaApiError, to_minor, _num
from app.models import Contact, Property

MIN_REACH = 200          # below this a reel has not been seen enough to judge
MAX_REELS = 25
TOP_N = 5
_SPLIT = re.compile(r"[^a-z]+")


# ---------------------------------------------------------------------------
# What the CRM knows about demand
# ---------------------------------------------------------------------------


def _base_area(location: str) -> str | None:
    """'Malad West', 'Malad west', 'Link Road Malad West' all want to land on
    the same key a caption would use: the area's name."""
    words = [w for w in _SPLIT.split(location.lower()) if w]
    for w in words:
        if len(w) >= 5 and w not in _GENERIC:
            return w
    return None


_GENERIC = {"west", "east", "north", "south", "road", "nagar", "link", "complex", "society", "tower", "heights"}


def area_demand(db: DbSession) -> dict[str, dict[str, int]]:
    """area -> {"leads": n, "listings": n}, from the owner's own data."""
    stats: dict[str, Counter] = {}
    with system_scope():
        lead_locs = db.execute(
            text("SELECT unnest(preferred_locations) FROM contacts WHERE deleted_at IS NULL")
        ).scalars()
        prop_locs = db.execute(
            select(Property.location).where(Property.deleted_at.is_(None))
        ).scalars()
        for kind, rows in (("leads", lead_locs), ("listings", prop_locs)):
            for loc in rows:
                key = _base_area(loc or "")
                if key:
                    stats.setdefault(key, Counter())[kind] += 1
    return {k: {"leads": v["leads"], "listings": v["listings"]} for k, v in stats.items()}


# ---------------------------------------------------------------------------
# Reading and scoring reels
# ---------------------------------------------------------------------------


def fetch_reels(graph: GraphAds, ig_id: str) -> list[dict]:
    media = [
        m
        for m in graph.ig_media(ig_id, limit=50)
        if (m.get("media_product_type") or "").upper() == "REELS"
        or (m.get("media_type") or "").upper() == "VIDEO"
    ][:MAX_REELS]
    with ThreadPoolExecutor(max_workers=6) as pool:
        insights = list(pool.map(lambda m: graph.media_insights(m["id"]), media))
    reels = []
    for m, ins in zip(media, insights):
        reach = ins.get("reach", 0.0)
        likes = ins.get("likes", _num(m.get("like_count")))
        comments = ins.get("comments", _num(m.get("comments_count")))
        shares = ins.get("shares", 0.0)
        saved = ins.get("saved", 0.0)
        weighted = likes + 2 * comments + 3 * shares + 3 * saved
        reels.append(
            {
                "media_id": m["id"],
                "caption": (m.get("caption") or "").strip(),
                "permalink": m.get("permalink"),
                "thumbnail_url": m.get("thumbnail_url"),
                "posted_at": m.get("timestamp"),
                "views": int(ins.get("views", 0)),
                "reach": int(reach),
                "likes": int(likes),
                "comments": int(comments),
                "shares": int(shares),
                "saved": int(saved),
                "engagement_rate": round(weighted / reach * 100, 2) if reach else 0.0,
                "_weighted": weighted / reach if reach else 0.0,
            }
        )
    return reels


def score_reels(reels: list[dict]) -> list[dict]:
    """0-100: half distance travelled, half how hard it held people, each
    relative to the best reel on the account (so it ranks *your* reels against
    each other rather than against an industry average nobody can verify)."""
    judged = [r for r in reels if r["reach"] >= MIN_REACH]
    top_reach = max((r["reach"] for r in judged), default=0) or 1
    top_eng = max((r["_weighted"] for r in judged), default=0) or 1
    for r in reels:
        if r["reach"] >= MIN_REACH:
            r["score"] = round(50 * r["reach"] / top_reach + 50 * r["_weighted"] / top_eng)
        else:
            r["score"] = None
    ranked = sorted(reels, key=lambda r: (r["score"] is None, -(r["score"] or 0), -r["reach"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


def _round_budget(value: float) -> int:
    return max(100, int(round(value / 50.0) * 50))


def build_suggestions(reels: list[dict], demand: dict[str, dict[str, int]], currency: str | None) -> list[dict]:
    ranked = score_reels(reels)
    base = settings.meta_default_daily_budget
    cities = [c.strip() for c in settings.meta_target_cities.split(",") if c.strip()]
    out: list[dict] = []
    for r in ranked:
        caption_l = r["caption"].lower()
        matched = [
            {"area": a.title(), **d}
            for a, d in sorted(demand.items(), key=lambda kv: -(kv[1]["leads"] * 3 + kv[1]["listings"]))
            if a in caption_l
        ][:3]
        reasons, verdict, campaign = [], "skip", None
        if r["score"] is None:
            verdict = "not_enough_data"
            reasons.append(f"Only {r['reach']:,} accounts reached so far - too few to judge. Check again after a few days.")
        else:
            verdict = "strong" if r["score"] >= 70 else "decent" if r["score"] >= 40 else "weak"
            reasons.append(f"Reached {r['reach']:,} accounts with {r['views']:,} views.")
            if r["shares"] or r["saved"]:
                reasons.append(f"{r['shares']} shares and {r['saved']} saves - people kept this to come back to.")
            reasons.append(f"Engagement {r['engagement_rate']}% of reach.")
            for m in matched:
                bits = []
                if m["leads"]:
                    bits.append(f"{m['leads']} of your leads ask for it")
                if m["listings"]:
                    bits.append(f"{m['listings']} listings in inventory")
                if bits:
                    reasons.append(f"Mentions {m['area']}: " + " and ".join(bits) + ".")
            if verdict != "weak" and len([o for o in out if o["campaign"]]) < TOP_N:
                budget = _round_budget(base * (0.5 + 0.5 * r["score"] / 100))
                campaign = {
                    "name": f"Reel boost - {(r['caption'] or 'Reel')[:40].strip()}",
                    "objective": "Leads (instant form)",
                    "daily_budget": budget,
                    "currency": currency,
                    "cities": cities or ["Mumbai"],
                    "age_min": 25,
                    "age_max": 55,
                }
        out.append(
            {
                **{k: v for k, v in r.items() if not k.startswith("_")},
                "verdict": verdict,
                "reasons": reasons,
                "matched_areas": matched,
                "campaign": campaign,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Creating a paused campaign from a reel
# ---------------------------------------------------------------------------


def create_paused_campaign(
    graph: GraphAds,
    *,
    account_id: str,
    currency: str | None,
    page_id: str,
    instagram_id: str,
    media_id: str,
    form_id: str,
    name: str,
    daily_budget: Decimal,
    cities: list[str],
    age_min: int,
    age_max: int,
) -> dict[str, Any]:
    """Campaign -> ad set -> creative -> ad, all PAUSED. If any step after the
    campaign fails the campaign is deleted, so a half-built structure is never
    left in Ads Manager for someone to find and un-pause."""
    geo_cities = []
    for city in cities:
        hit = graph.geo_search(city)
        if hit and hit.get("key"):
            geo_cities.append({"key": hit["key"], "radius": 25, "distance_unit": "kilometer"})
    geo = {"cities": geo_cities} if geo_cities else {"countries": ["IN"]}

    import json

    campaign_id = graph.create_campaign(account_id, name)
    try:
        adset_id = graph.create_adset(
            account_id,
            {
                "name": f"{name} - ad set",
                "campaign_id": campaign_id,
                "daily_budget": str(to_minor(daily_budget, currency)),
                "billing_event": "IMPRESSIONS",
                "optimization_goal": "LEAD_GENERATION",
                "destination_type": "ON_AD",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "promoted_object": json.dumps({"page_id": page_id}),
                "targeting": json.dumps(
                    {
                        "geo_locations": geo,
                        "age_min": age_min,
                        "age_max": age_max,
                        "publisher_platforms": ["instagram"],
                        "instagram_positions": ["stream", "reels"],
                        "targeting_automation": {"advantage_audience": 0},
                    }
                ),
                "status": "PAUSED",
            },
        )
        creative_id = graph.create_creative(
            account_id,
            {
                "name": f"{name} - creative",
                "instagram_user_id": instagram_id,
                "source_instagram_media_id": media_id,
                "call_to_action": json.dumps(
                    {"type": "SIGN_UP", "value": {"lead_gen_form_id": form_id}}
                ),
            },
        )
        ad_id = graph.create_ad(
            account_id,
            {
                "name": f"{name} - ad",
                "adset_id": adset_id,
                "creative": json.dumps({"creative_id": creative_id}),
                "status": "PAUSED",
            },
        )
    except MetaApiError:
        try:
            graph.delete(campaign_id)
        except Exception:  # best effort; the error below is what the user needs
            pass
        raise
    return {
        "campaign_id": campaign_id,
        "adset_id": adset_id,
        "creative_id": creative_id,
        "ad_id": ad_id,
        "targeted_cities": len(geo_cities),
    }
