"""Development seed data.

    python -m app.seed --reset

Creates one owner, two agents, two cold callers, a small book of leads, an
inventory, and enough call/showing history that the owner's feed and the
"who showed what to whom" timeline have something real to display.

Resetting connects as the migrator role: the application role cannot truncate
audit_log, which is the correct production behaviour and exactly why the reset
path is separate.
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, system_scope
from app.models import (
    Activity,
    CallLog,
    Contact,
    Property,
    PropertyInterest,
    Task,
    User,
)
from app.security import hash_password

TABLES = (
    "audit_log",
    "push_subscriptions",
    "tasks",
    "sessions",
    "activities",
    "call_logs",
    "property_interests",
    "contacts",
    "properties",
    "users",
)

PASSWORD = "balaji123"

LOCATIONS = [
    "Bandra West",
    "Andheri East",
    "Powai",
    "Lower Parel",
    "Chembur",
    "Thane West",
    "Goregaon East",
    "Malad West",
]
BUILDINGS = [
    "Rustomjee Seasons",
    "Lodha Bellissimo",
    "Hiranandani Gardens",
    "Oberoi Splendor",
    "Kalpataru Radiance",
    "Godrej Emerald",
    "Runwal Greens",
]
FIRST = [
    "Rohit", "Priya", "Anil", "Sneha", "Vikram", "Neha", "Arjun", "Kavita",
    "Sameer", "Divya", "Rahul", "Pooja", "Karan", "Meera", "Nikhil", "Aditi",
    "Suresh", "Ritu", "Manish", "Shweta", "Deepak", "Anjali", "Varun", "Tanvi",
]
LAST = [
    "Mehta", "Shah", "Kulkarni", "Iyer", "Nair", "Patel", "Desai", "Joshi",
    "Rao", "Gupta", "Banerjee", "Chopra", "Reddy", "Malhotra",
]


def reset() -> None:
    engine = create_engine(settings.sqlalchemy_migration_url)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    engine.dispose()
    print("Truncated all tables (as the migrator role).")


def seed() -> None:
    rng = random.Random(20260810)
    now = datetime.now(timezone.utc)

    db: Session = SessionLocal()
    with system_scope():
        try:
            owner = User(
                name="Balaji Rao",
                email="owner@balaji.local",
                phone="+91 98200 10001",
                role="owner",
                password_hash=hash_password(PASSWORD),
            )
            agents = [
                User(
                    name="Priya Nair",
                    email="priya@balaji.local",
                    phone="+91 98200 10002",
                    role="agent",
                    password_hash=hash_password(PASSWORD),
                ),
                User(
                    name="Vikram Shah",
                    email="vikram@balaji.local",
                    phone="+91 98200 10003",
                    role="agent",
                    password_hash=hash_password(PASSWORD),
                ),
            ]
            callers = [
                User(
                    name="Sneha Kulkarni",
                    email="sneha@balaji.local",
                    phone="+91 98200 10004",
                    role="cold_caller",
                    password_hash=hash_password(PASSWORD),
                ),
                User(
                    name="Arjun Desai",
                    email="arjun@balaji.local",
                    phone="+91 98200 10005",
                    role="cold_caller",
                    password_hash=hash_password(PASSWORD),
                ),
            ]
            staff = [owner, *agents, *callers]
            db.add_all(staff)
            db.flush()

            properties: list[Property] = []
            for i in range(34):
                listing_type = rng.choice(["rent", "outright"])
                bhk = rng.choice([1, 2, 3, 4])
                location = rng.choice(LOCATIONS)
                building = rng.choice(BUILDINGS)
                price = (
                    rng.randrange(35_000, 350_000, 5_000)
                    if listing_type == "rent"
                    else rng.randrange(9_000_000, 145_000_000, 500_000)
                )
                prop = Property(
                    title=f"{bhk} BHK in {building}",
                    location=location,
                    building=building,
                    property_type=rng.choice(
                        ["apartment", "apartment", "apartment", "villa", "commercial"]
                    ),
                    listing_type=listing_type,
                    price=price,
                    status=rng.choice(
                        ["available"] * 8 + ["blocked"] * 2 + ["sold"]
                    ),
                    source="manual",
                    posted_by_agent_id=rng.choice(agents + [owner]).id,
                    created_at=now - timedelta(days=rng.randint(0, 90)),
                )
                properties.append(prop)
            db.add_all(properties)
            db.flush()

            contacts: list[Contact] = []
            for i in range(46):
                assignee = rng.choice(agents + callers)
                budget_min = rng.randrange(4_000_000, 40_000_000, 500_000)
                created = now - timedelta(days=rng.randint(0, 60))
                contacts.append(
                    Contact(
                        first_name=rng.choice(FIRST),
                        last_name=rng.choice(LAST),
                        email=f"lead{i}@example.com",
                        phone=f"+91 9{rng.randrange(100000000, 999999999)}",
                        # Most leads start masked, which is the production
                        # default for staff-created leads.
                        phone_masked=rng.random() < 0.7,
                        lead_source=rng.choice(
                            ["instagram", "walk_in", "referral", "portal", "whatsapp_group"]
                        ),
                        budget_min=budget_min,
                        budget_max=budget_min + rng.randrange(1_000_000, 20_000_000, 500_000),
                        preferred_locations=rng.sample(LOCATIONS, rng.randint(1, 3)),
                        property_type_interest=rng.choice(
                            ["apartment", "apartment", "villa", "commercial"]
                        ),
                        buyer_type=rng.choice(["end_user", "end_user", "investor"]),
                        stage="new",
                        owner_id=assignee.id,
                        created_at=created,
                        updated_at=created,
                    )
                )
            db.add_all(contacts)
            db.flush()

            outcomes = [
                "connected",
                "not_reachable",
                "interested",
                "callback_requested",
                "not_interested",
                "wrong_number",
            ]
            weights = [30, 25, 15, 15, 10, 5]

            for contact in contacts:
                worker = next(u for u in staff if u.id == contact.owner_id)

                for _ in range(rng.randint(0, 3)):
                    when = contact.created_at + timedelta(
                        hours=rng.randint(2, 24 * 30)
                    )
                    if when > now:
                        continue
                    outcome = rng.choices(outcomes, weights)[0]
                    temperature = (
                        rng.choice(["hot", "warm", "cold"])
                        if outcome in ("connected", "interested", "callback_requested")
                        else None
                    )
                    flagged = outcome == "interested" and temperature == "hot" and rng.random() < 0.4
                    call = CallLog(
                        contact_id=contact.id,
                        caller_id=worker.id,
                        outcome=outcome,
                        temperature=temperature,
                        notes=rng.choice(
                            [
                                "Wants a 3BHK with parking, budget is firm.",
                                "Asked to call back after 7pm.",
                                "Comparing two projects, needs a site visit.",
                                "Investor — looking for rental yield above 3.5%.",
                                None,
                            ]
                        ),
                        flagged_for_owner=flagged,
                        created_at=when,
                    )
                    db.add(call)
                    db.flush()

                    if contact.stage == "new":
                        contact.stage = "contacted"
                        contact.updated_at = when

                    if outcome == "callback_requested":
                        db.add(
                            Task(
                                contact_id=contact.id,
                                assigned_to=worker.id,
                                created_by=worker.id,
                                title=f"Follow up with {contact.full_name} (callback requested)",
                                # A mix of overdue and upcoming, so the queue's
                                # priority ordering is visible in the seed data.
                                due_at=when + timedelta(hours=rng.choice([12, 24, 72, -6])),
                                status="pending",
                                source_call_log_id=call.id,
                                created_at=when,
                            )
                        )

                # Showings, by agents only -- cold callers do not show property.
                if worker.role == "agent" and rng.random() < 0.55:
                    for _ in range(rng.randint(1, 3)):
                        prop = rng.choice(properties)
                        when = contact.created_at + timedelta(days=rng.randint(1, 45))
                        if when > now:
                            continue
                        level = rng.choices(
                            [
                                "inquired",
                                "site_visit_scheduled",
                                "site_visit_done",
                                "negotiating",
                            ],
                            [30, 25, 35, 10],
                        )[0]
                        db.add(
                            PropertyInterest(
                                contact_id=contact.id,
                                property_id=prop.id,
                                shown_by_agent_id=worker.id,
                                interest_level=level,
                                shown_at=when,
                            )
                        )
                        db.add(
                            Activity(
                                contact_id=contact.id,
                                property_id=prop.id,
                                user_id=worker.id,
                                type="site_visit"
                                if level in ("site_visit_done", "negotiating")
                                else "note",
                                body=f"{level.replace('_', ' ').title()} — {prop.title}, {prop.location}",
                                occurred_at=when,
                            )
                        )
                        stage = {
                            "inquired": "contacted",
                            "site_visit_scheduled": "site_visit_scheduled",
                            "site_visit_done": "visited",
                            "negotiating": "negotiating",
                        }[level]
                        contact.stage = stage
                        contact.updated_at = max(contact.updated_at, when)

            db.commit()
        finally:
            db.close()

    print(
        "Seeded.\n"
        f"  Owner        owner@balaji.local   / {PASSWORD}\n"
        f"  Agent        priya@balaji.local   / {PASSWORD}\n"
        f"  Agent        vikram@balaji.local  / {PASSWORD}\n"
        f"  Cold caller  sneha@balaji.local   / {PASSWORD}\n"
        f"  Cold caller  arjun@balaji.local   / {PASSWORD}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset", action="store_true", help="Truncate all tables before seeding."
    )
    args = parser.parse_args()
    if args.reset:
        reset()
    seed()
