"""SQLAlchemy models.

Tables and columns mirror `docs/DATA_MODEL.md` exactly. The tables below are
additive to that document, each an explicit deviation:

* ``sessions``           -- API_SPEC's ``POST /auth/logout`` promises to
                            invalidate a token, which a stateless JWT cannot do.
                            Tokens carry a ``jti`` that must be present and
                            un-revoked here, so logout and account deactivation
                            kill live tokens (SECURITY_MODEL.md §"Session &
                            device controls").
* ``tasks``              -- FEATURE_LIST P1 requires follow-up reminders with an
                            open/done state, which an append-only activity log
                            cannot express.
* ``push_subscriptions`` -- Web Push endpoints per user/device for the PWA.

Phase 3 (WhatsApp Property Feed Aggregator) adds three more, plus columns on
``properties``. DATA_MODEL.md anticipated the feature with ``source``,
``raw_message`` and ``source_group`` on ``properties`` but modelled a listing as
arriving exactly once, from one message. In practice the same flat is reposted
across many groups by many brokers, which is the reason dedup exists at all --
so provenance has to be its own table:

* ``whatsapp_groups``    -- the monitored groups, owner-managed. The ingestion
                            gateway reads this to know what to forward.
* ``whatsapp_messages``  -- every forwarded message, stored raw and verbatim
                            before any parsing, with the extraction job's state
                            machine on it. Raw-first means a prompt or parser
                            fix can be replayed over history instead of the
                            data being lost to a bad early extraction.
* ``property_sources``   -- one row per (property, message) sighting. This is
                            what ARCHITECTURE.md's "attach as an additional
                            source reference rather than creating a new row"
                            step writes, and it is what lets the owner see that
                            a listing came from four brokers in three groups.

The extra ``properties`` columns (``bhk``, ``area_sqft``, ``furnishing``,
``contact_phone``, ``contact_name``, ``dedupe_key``, ``extraction_confidence``,
``last_seen_at``, ``review_state``) exist because dedup needs them: matching on
location and price alone merges a 2BHK with the 3BHK upstairs. They are
populated by the extractor and are all nullable, so a manually-entered listing
is unaffected.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Domain vocabularies. Kept as plain tuples rather than PG enums so the values
# stay identical to the SQL comments in DATA_MODEL.md and remain cheap to
# extend in later phases.
# --------------------------------------------------------------------------

ROLE_OWNER = "owner"
ROLE_MANAGER = "manager"  # defined in the model; Phase 2 activates it
ROLE_AGENT = "agent"
ROLE_COLD_CALLER = "cold_caller"
ROLES = (ROLE_OWNER, ROLE_MANAGER, ROLE_AGENT, ROLE_COLD_CALLER)

# PHASES.md: Phase 1 ships Owner / Agent / Cold Caller only.
PHASE1_ROLES = (ROLE_OWNER, ROLE_AGENT, ROLE_COLD_CALLER)

STAGES = (
    "new",
    "contacted",
    "site_visit_scheduled",
    "visited",
    "negotiating",
    "closed",
    "lost",
)

CALL_OUTCOMES = (
    "connected",
    "not_reachable",
    "not_interested",
    "interested",
    "callback_requested",
    "wrong_number",
)
TEMPERATURES = ("hot", "warm", "cold")

# FEATURE_LIST P1: outcomes that automatically create a follow-up task.
FOLLOW_UP_OUTCOMES = ("callback_requested", "interested")

INTEREST_LEVELS = (
    "inquired",
    "site_visit_scheduled",
    "site_visit_done",
    "negotiating",
)

ACTIVITY_TYPES = ("site_visit", "note", "stage_change", "follow_up")

PROPERTY_STATUSES = ("available", "blocked", "sold")
LISTING_TYPES = ("rent", "outright")
PROPERTY_TYPES = ("apartment", "villa", "plot", "commercial")

PROPERTY_SOURCES = ("manual", "whatsapp_group")

# Where an ingested listing sits in the owner's review flow. Extraction is
# probabilistic, so a low-confidence listing is published but marked, rather
# than either silently trusted or silently dropped.
REVIEW_STATES = ("auto_accepted", "needs_review", "confirmed", "rejected")

# --- WhatsApp ingestion (Phase 3) -----------------------------------------
#
# The message state machine. A message only ever moves forward, and every
# terminal state is distinguishable, because "we saw it and it wasn't a
# listing" and "we saw it and parsing blew up" need very different responses
# from the owner watching the feed.
INGEST_PENDING = "pending"        # stored, not yet sent to the extractor
INGEST_PROCESSING = "processing"  # claimed by a worker
INGEST_EXTRACTED = "extracted"    # produced at least one new property
INGEST_DUPLICATE = "duplicate"    # parsed fine; every listing already existed
INGEST_NOT_LISTING = "not_listing"  # group chatter, not inventory
INGEST_FAILED = "failed"          # extractor errored; retryable up to a cap
INGEST_STATUSES = (
    INGEST_PENDING,
    INGEST_PROCESSING,
    INGEST_EXTRACTED,
    INGEST_DUPLICATE,
    INGEST_NOT_LISTING,
    INGEST_FAILED,
)

# A message that has failed this many times stops being retried. Without a cap
# one malformed message is re-sent to the model forever, which is a bill, not
# a bug report.
MAX_EXTRACTION_ATTEMPTS = 3


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    phone: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    manager_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )  # team scoping, Phase 2
    is_available: Mapped[bool | None] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    # When true, staff below Owner/Manager see only the last 4 digits until
    # they have logged a qualifying interaction on this contact.
    phone_masked: Mapped[bool | None] = mapped_column(Boolean, default=False)
    lead_source: Mapped[str | None] = mapped_column(Text)
    campaign: Mapped[str | None] = mapped_column(Text)
    budget_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    budget_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    preferred_locations: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    property_type_interest: Mapped[str | None] = mapped_column(Text)
    # 'rent' or 'outright', the same vocabulary as Property.listing_type. The
    # inventory side is NOT NULL because a listing that does not say is not a
    # listing; this side is nullable because leads predate the question.
    listing_type_interest: Mapped[str | None] = mapped_column(Text)
    # How many bedrooms the lead is after, in the same units as Property.bhk so
    # the two compare without translation. 4 reads as "4 or more" on both.
    bhk: Mapped[int | None] = mapped_column(Integer)
    buyer_type: Mapped[str | None] = mapped_column(Text)
    # Free text for everything the fields above cannot hold -- possession
    # timelines, who actually decides, what they have already rejected.
    remarks: Mapped[str | None] = mapped_column(Text)
    lead_score: Mapped[int | None] = mapped_column(Integer, default=0)
    stage: Mapped[str | None] = mapped_column(Text, default="new")
    # A row from a purchased calling list is a phone number, not a lead. It sits
    # in a caller's queue and stays out of the leads pipeline until someone has
    # actually spoken to the person and flagged them — see CallLog.marked_lead.
    # Contacts created any other way (walk-in, referral, portal) are leads from
    # the moment they exist, which is why this defaults to true.
    is_lead: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    # Which uploaded spreadsheet this came from, so the owner can tell which
    # lists are worth buying again. Null for everything not imported.
    batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("lead_batches.id")
    )
    owner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_contacts_owner", "owner_id"),
        Index(
            "idx_contacts_phone",
            "phone",
            postgresql_where=(deleted_at.is_(None)),
        ),
        # Every batch performance figure groups by this, and the leads list
        # filters on is_lead, so the two travel together.
        Index("idx_contacts_batch", "batch_id", "is_lead"),
        # The leads screen filters by size on top of the is_lead narrowing it
        # always applies, so the two travel together here as well.
        Index("idx_contacts_bhk", "bhk", "is_lead"),
        Index("idx_contacts_listing_type", "listing_type_interest", "is_lead"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name or ''}".strip()


# What the gateway is currently doing, as far as the API knows. The owner's
# screen is built entirely from this, so the vocabulary is chosen to be
# answerable from the browser without guessing:
WA_DISCONNECTED = "disconnected"   # gateway not running, or has not reported yet
WA_CONNECTING = "connecting"       # socket opening
WA_QR = "qr"                       # waiting for a phone to scan `qr`
WA_CONNECTED = "connected"         # linked and reading
WA_LOGGED_OUT = "logged_out"       # device removed from the phone; needs re-pair
WA_SESSION_STATES = (
    WA_DISCONNECTED,
    WA_CONNECTING,
    WA_QR,
    WA_CONNECTED,
    WA_LOGGED_OUT,
)


class WhatsAppSession(Base):
    """The gateway's connection state, so pairing can happen in the browser.

    Pairing was terminal-only: run `npm run pair`, scan the QR printed as ASCII.
    That is fine for the person who deployed it and useless for the owner, who
    is the one holding the phone.

    Exactly one row. The gateway reports into it and the owner's screen polls
    it. The QR itself is short-lived — WhatsApp rotates it every twenty seconds
    or so — which is why `qr_expires_at` is stored rather than inferred: a
    stale QR that still renders is worse than none, because it fails silently
    on the phone with no explanation.
    """

    __tablename__ = "whatsapp_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=WA_DISCONNECTED
    )
    qr: Mapped[str | None] = mapped_column(Text)
    qr_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Which account is linked, so the owner can see at a glance that it is the
    # dedicated number and not somebody's personal one.
    jid: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    # Heartbeat. A gateway that has crashed leaves `state` saying "connected"
    # forever; the screen uses this to say "last heard from 20 minutes ago"
    # instead of showing a comforting lie.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Commands, owner's screen -> gateway. The gateway polls, acts, and clears
    # them by reporting. Timestamps rather than flags because "asked for 40
    # seconds ago" is what the UI needs to show while it waits, and a flag only
    # says "yes".
    pair_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    sync_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    directory_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class WhatsAppGroupCandidate(Base):
    """Every group the linked account is in — the picker's source list.

    Not a decision, a cache: a row here means WhatsApp told the gateway this
    group exists. Watching it is still a ``WhatsAppGroup`` row, which is what
    the ingest webhook checks and what the audit log records. Keeping the two
    apart is what stops "we can see this group" from ever meaning "we are
    reading this group".

    Guarded in ``app/db.py`` for the same reason as the rest of the WhatsApp
    tables: the list of groups a brokerage sits in is commercially revealing,
    and it is Owner-only under ``whatsapp.manage``.
    """

    __tablename__ = "whatsapp_group_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_jid: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Empty rather than null when metadata has not synced yet. A group whose
    # subject has not arrived is still worth listing — WhatsApp sends it moments
    # later, and one nameless group must not hide the rest.
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    participants: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContactAssignment(Base):
    """An extra staff member working a lead, beyond its owner.

    ``Contact.owner_id`` answers "whose lead is this" and stays single: one
    person is accountable, and the call queue is built from it. This table
    answers the different question of who else has been asked to work it —
    a closer brought in on a hot lead, two agents covering different sites.

    Kept as rows rather than an array column because each one carries who
    assigned it and when, which is what makes the audit trail readable, and
    because the scoping predicate in app/scoping.py has to join against it.
    """

    __tablename__ = "contact_assignments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contacts.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    assigned_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Assigning the same person twice is a no-op, not a second assignment.
        UniqueConstraint("contact_id", "user_id", name="uq_assignment_pair"),
        # Both directions are hot: the scoping predicate looks up by user, the
        # contact detail screen looks up by contact.
        Index("idx_assignments_user", "user_id"),
        Index("idx_assignments_contact", "contact_id"),
    )


class LeadBatch(Base):
    """One uploaded calling list.

    The owner buys these lists, and the only question that matters afterwards is
    whether a given list was worth the money. Grouping the rows under a named
    batch is what makes that answerable — without it, a spreadsheet dissolves
    into the contact table on import and its performance can never be recovered.
    """

    __tablename__ = "lead_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )
    # What the file contained, kept even though the rows themselves may have
    # been rejected: "600 rows in, 480 usable" is the useful comparison between
    # two vendors, and it is unrecoverable once the duplicates are dropped.
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    building: Mapped[str | None] = mapped_column(Text)
    property_type: Mapped[str | None] = mapped_column(Text)
    listing_type: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str | None] = mapped_column(Text, default="available")
    source: Mapped[str | None] = mapped_column(Text, default="manual")
    raw_message: Mapped[str | None] = mapped_column(Text)  # Phase 3
    source_group: Mapped[str | None] = mapped_column(Text)  # Phase 3
    posted_by_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # -- Phase 3 extraction columns (see module docstring) ------------------
    # Nullable throughout: a manually-entered listing leaves all of them unset
    # and behaves exactly as it did in Phase 1.
    bhk: Mapped[int | None] = mapped_column(Integer)
    area_sqft: Mapped[int | None] = mapped_column(Integer)
    furnishing: Mapped[str | None] = mapped_column(Text)
    # The broker who posted, from the message itself. This is a counterparty's
    # number, not a firm lead, so it is deliberately *not* in `contacts` -- it
    # must never appear in the client list or an export of it.
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    # Coarse blocking key for dedup: equal keys are *candidates*, not matches.
    # The fuzzy pass in app/property_dedup.py decides. Indexed because it is
    # the first lookup on every ingested listing.
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    review_state: Mapped[str | None] = mapped_column(Text)
    # Bumped every time the listing is seen again, in any group. A reposted
    # listing is a live listing; one nobody has mentioned in a month probably
    # is not.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_properties_location", "location"),
        Index("idx_properties_listing_type", "listing_type"),
        Index("idx_properties_price", "price"),
        Index(
            "idx_properties_dedupe_key",
            "dedupe_key",
            postgresql_where=(deleted_at.is_(None)),
        ),
        Index("idx_properties_source", "source"),
    )


class PropertyInterest(Base):
    """One row per showing. The backbone of "who showed what to whom"."""

    __tablename__ = "property_interests"

    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"))
    property_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("properties.id"))
    shown_by_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )
    interest_level: Mapped[str | None] = mapped_column(Text)
    shown_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Composite key, not a unique pair: the same agent may legitimately show the
    # same property to the same client more than once, and each showing is its
    # own event (DATA_MODEL.md notes).
    __table_args__ = (
        PrimaryKeyConstraint("contact_id", "property_id", "shown_at"),
    )


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id")
    )
    caller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    flagged_for_owner: Mapped[bool | None] = mapped_column(Boolean, default=False)
    # The caller judged this number to be a real prospect, which is the only
    # thing that turns an imported row into a lead. Recorded on the call rather
    # than only on the contact so the batch reports can attribute the decision
    # to a person and a moment.
    marked_lead: Mapped[bool | None] = mapped_column(Boolean, default=False)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_call_logs_contact", "contact_id", created_at.desc()),
        Index(
            "idx_call_logs_flagged",
            "flagged_for_owner",
            postgresql_where=(flagged_for_owner.is_(True)),
        ),
    )


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id")
    )
    property_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("properties.id")
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_activities_contact", "contact_id", occurred_at.desc()),)


class AuditLog(Base):
    """Append-only. The app's DB role has no UPDATE/DELETE grant on this table.

    Deliberately has no ``deleted_at``: nothing in the application, including
    Owner-role UI actions, may edit or remove audit history.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_audit_log_user", "user_id", occurred_at.desc()),
        Index("idx_audit_log_resource", "resource_type", "resource_id"),
    )


# ---------------------------------------------------------------------------
# Additive tables (see module docstring)
# ---------------------------------------------------------------------------


class Session(Base):
    """Server-side record making an issued JWT revocable."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    # When the password was actually typed. Carried forward across renewals so
    # that sliding a session can never outrun the absolute cap.
    chain_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # When this session was last renewed. Null until the first renewal.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_sessions_user", "user_id", "revoked_at"),
        Index(
            "idx_sessions_live",
            "user_id",
            "expires_at",
            postgresql_where=(revoked_at.is_(None)),
        ),
    )


class Task(Base):
    """Follow-up reminder. Auto-created on qualifying call outcomes."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id")
    )
    assigned_to: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending"
    )  # 'pending', 'done', 'cancelled'
    source_call_log_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("call_logs.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_tasks_assignee_due", "assigned_to", "status", "due_at"),)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# WhatsApp Property Feed Aggregator (Phase 3)
# ---------------------------------------------------------------------------


class WhatsAppGroup(Base):
    """A monitored WhatsApp group.

    The gateway polls this table's active rows to decide what to forward, so
    the owner turning a noisy group off in the UI actually stops the ingest at
    the source rather than filtering it after the fact.
    """

    __tablename__ = "whatsapp_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # WhatsApp's own group id ("...@g.us"). Unique so the gateway can upsert on
    # it while the human-facing name stays editable and can change upstream.
    group_jid: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Free-text hint passed to the extractor, e.g. "Andheri West rentals only".
    # Group-level context measurably improves extraction on terse messages.
    note: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_whatsapp_groups_active", "is_active"),)


class WhatsAppMessage(Base):
    """One raw forwarded message, plus the extraction job's state.

    Stored verbatim *before* extraction runs. That ordering is the point: the
    gateway's job is to lose nothing, and the extractor's job is to interpret.
    When a prompt improves, history can be replayed.
    """

    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whatsapp_groups.id"), nullable=False
    )
    # WhatsApp's per-message id. Unique, and the ingest endpoint relies on that
    # for idempotency: the gateway reconnecting and replaying its buffer must
    # not double-create inventory.
    wa_message_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sender_jid: Mapped[str | None] = mapped_column(Text)
    sender_name: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=INGEST_PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    # The extractor's raw structured output, kept for debugging and for the
    # owner's review screen -- so "why did it think this was a 3BHK" is
    # answerable without re-running the model.
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How many properties this message created vs. merged into existing rows.
    listings_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        # The worker's claim query: oldest pending first, so a backlog drains
        # in the order it arrived.
        Index("idx_whatsapp_messages_queue", "status", "received_at"),
        Index("idx_whatsapp_messages_group", "group_id", received_at.desc()),
    )


class PropertySource(Base):
    """One sighting of a property in a message.

    A listing reposted by four brokers is one ``properties`` row and four rows
    here. Keeping sightings separate is what makes the dedup step non-lossy:
    merging never discards who posted what, when, or where.
    """

    __tablename__ = "property_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("properties.id"), nullable=False
    )
    message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whatsapp_messages.id")
    )
    group_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whatsapp_groups.id")
    )
    group_name: Mapped[str | None] = mapped_column(Text)
    posted_by_name: Mapped[str | None] = mapped_column(Text)
    posted_by_phone: Mapped[str | None] = mapped_column(Text)
    raw_message: Mapped[str | None] = mapped_column(Text)
    # 'origin' for the sighting that created the property, 'duplicate' for a
    # later one that merged into it.
    relation: Mapped[str] = mapped_column(Text, nullable=False, default="origin")
    match_score: Mapped[float | None] = mapped_column(Float)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # One sighting per (property, message): re-running the extractor over a
        # message must be idempotent rather than inflating the repost count.
        UniqueConstraint("property_id", "message_id", name="uq_property_source"),
        Index("idx_property_sources_property", "property_id", seen_at.desc()),
    )


# Name of the row the extraction loop keeps warm. A constant because two
# processes write it and one reads it, and a typo would look exactly like a
# worker that had stopped.
EXTRACTION_WORKER = "extraction"


class WorkerHeartbeat(Base):
    """Proof that a background loop is alive, so the UI can stop guessing.

    Extraction can run in its own service, in a thread inside the API, or in a
    terminal on someone's laptop. The API can only see the second, which is why
    the feed screen used to infer "the worker may not be running" from a queue
    that had grown past twenty — a guess that is wrong in both directions. It
    stays silent while a handful of messages sit unprocessed for a week, and it
    accuses a perfectly healthy worker that is merely behind after a busy
    morning.

    The loop writes here instead. Absence of a recent beat is then a fact about
    the deployment rather than an inference from its symptoms.

    Not in ``db.GUARDED_MAPPERS``: it holds no one's data, so there is no
    "whose is this?" for a scope filter to answer.
    """

    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)
