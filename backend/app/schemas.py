"""Request and response models.

Response shapes are derived from DATA_MODEL.md columns. The one place a
response deliberately diverges from the stored row is contact phone/email,
which passes through ``app/masking.py`` first.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None = None
    phone: str | None = None
    role: str
    manager_id: int | None = None
    is_available: bool | None = None
    created_at: datetime | None = None
    deleted_at: datetime | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


# Matches UserCreate's existing floor. Raising it would lock out staff whose
# accounts were created under the old rule and who now cannot change them —
# which is the very gap this feature exists to close.
MIN_PASSWORD_LENGTH = 8


class SessionReport(BaseModel):
    """The gateway telling the API what its WhatsApp socket is doing."""

    state: Literal["disconnected", "connecting", "qr", "connected", "logged_out"]
    qr: str | None = None
    # Seconds the QR stays valid. WhatsApp rotates roughly every 20s; the API
    # turns this into an absolute expiry so the browser is never comparing
    # against the gateway's clock.
    qr_ttl_seconds: int | None = Field(default=None, ge=1, le=300)
    jid: str | None = None
    display_name: str | None = None
    last_error: str | None = None


class SessionOut(BaseModel):
    """What the owner's pairing screen renders."""

    state: Literal["disconnected", "connecting", "qr", "connected", "logged_out"]
    qr: str | None = None
    qr_expires_at: datetime | None = None
    jid: str | None = None
    display_name: str | None = None
    last_error: str | None = None
    updated_at: datetime
    # True when the gateway has not reported recently enough to be believed.
    # A crashed gateway leaves state="connected" behind forever otherwise.
    stale: bool
    watched_groups: int


class Assignee(BaseModel):
    user_id: int
    name: str
    role: str
    assigned_by_name: str | None = None
    created_at: datetime
    note: str | None = None


class AssignRequest(BaseModel):
    """Who should be working this lead, besides its owner.

    The full desired set, not a delta: the UI is a list of checkboxes, and
    sending the state of that list means unticking someone removes them without
    a second call. A caller sending an empty list is clearing the assignments,
    which is a legitimate thing to want.
    """

    user_ids: list[int] = Field(
        description="Staff to assign. Send the complete set; omissions are removed."
    )
    note: str | None = Field(
        default=None,
        max_length=280,
        description="Why, shown on the task each assignee gets.",
    )
    due_at: datetime | None = Field(
        default=None, description="Deadline for the task. Defaults to 24h out."
    )


class AssignResponse(BaseModel):
    contact_id: int
    assignees: list[Assignee]
    added: list[str]
    removed: list[str]
    tasks_created: int


class PasswordChange(BaseModel):
    """Self-service change. The current password is required.

    Without it, anyone who reaches an unlocked laptop owns the account
    permanently rather than until it locks — a session is a temporary thing,
    a changed password is not.
    """

    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class PasswordChangeResponse(BaseModel):
    access_token: str
    expires_at: datetime
    sessions_revoked: int


class PasswordReset(BaseModel):
    """Owner resetting someone else's password.

    No current password: the whole point is that the staff member has lost it.
    Deliberately a separate endpoint from the self-service one so the
    capability check and the audit record are different things.
    """

    new_password: str | None = Field(
        default=None,
        min_length=MIN_PASSWORD_LENGTH,
        description="Omit to have one generated and returned once.",
    )


class PasswordResetResponse(BaseModel):
    user_id: int
    name: str
    # Present only when the server generated it. Never echoes a password the
    # caller supplied — they already have it, and returning it puts it in one
    # more log.
    generated_password: str | None = None
    sessions_revoked: int


class UserCreate(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    role: Literal["owner", "agent", "cold_caller"]
    phone: str | None = None


class UserWorkload(BaseModel):
    """A staff member plus what they are currently carrying.

    Powers the owner's team screen. Removing someone is only a safe decision
    with these numbers in view -- deactivating a cold caller holding 40 live
    leads silently strands all of them, and the owner needs to see that before
    they click, not after.
    """

    user: UserOut
    active_leads: int = 0
    open_tasks: int = 0
    overdue_tasks: int = 0
    calls_last_7d: int = 0
    showings_last_7d: int = 0
    last_active_at: datetime | None = None


class StaffPerformance(BaseModel):
    """One staff member's numbers over a window.

    FEATURE_LIST P2, "Team performance dashboard: leads per agent, conversion
    rate, response time, visit-to-close ratio".

    Counts are raw so the owner can judge them; the two derived figures
    (`connect_rate`, `conversion_rate`) are returned as fractions and are
    ``None`` rather than zero when the denominator is empty — a caller who has
    made no calls has no connect rate, which is a different statement from a
    connect rate of 0%.
    """

    user: UserOut

    calls: int = 0
    calls_by_outcome: dict[str, int] = Field(default_factory=dict)
    connected: int = 0
    connect_rate: float | None = None

    showings: int = 0
    escalations: int = 0

    leads_assigned: int = 0
    leads_by_stage: dict[str, int] = Field(default_factory=dict)
    closed: int = 0
    conversion_rate: float | None = None

    tasks_open: int = 0
    tasks_overdue: int = 0

    # Median hours between a lead being created and this person's first call on
    # it. Median, not mean: one lead left for three weeks would drag an average
    # far enough to hide an otherwise responsive caller.
    median_response_hours: float | None = None
    last_active_at: datetime | None = None


class TeamPerformance(BaseModel):
    days: int
    since: datetime
    staff: list[StaffPerformance]
    # Firm-wide totals for the same window, so a person's numbers can be read
    # against the team rather than in isolation.
    total_calls: int = 0
    total_showings: int = 0
    total_closed: int = 0


class ReassignLeadsRequest(BaseModel):
    to_user_id: int = Field(
        description="Staff member who inherits the leads. Must be active."
    )
    reason: str | None = None


class ReassignLeadsResponse(BaseModel):
    moved: int
    from_user_id: int
    to_user_id: int


class UserUpdate(BaseModel):
    name: str | None = None
    role: Literal["owner", "agent", "cold_caller"] | None = None
    manager_id: int | None = None
    is_available: bool | None = None
    phone: str | None = None
    deactivate: bool | None = Field(
        default=None,
        description=(
            "Soft-deletes the user and revokes every live session, so a "
            "departing staff member loses access immediately."
        ),
    )


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


class ContactBase(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    lead_source: str | None = None
    campaign: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    preferred_locations: list[str] | None = None
    property_type_interest: str | None = None
    buyer_type: Literal["end_user", "investor"] | None = None
    stage: str | None = None


class ContactCreate(ContactBase):
    owner_id: int | None = Field(
        default=None,
        description=(
            "Owner-only. Staff-created contacts are assigned to their creator; "
            "an Agent cannot create a lead in someone else's name."
        ),
    )


class ContactUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    lead_source: str | None = None
    campaign: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    preferred_locations: list[str] | None = None
    property_type_interest: str | None = None
    buyer_type: str | None = None
    stage: str | None = None
    owner_id: int | None = None
    phone_masked: bool | None = None
    lead_score: int | None = None


class ContactOut(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    # True when the values above were reduced before leaving the server.
    contact_details_masked: bool = False
    lead_source: str | None = None
    campaign: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    preferred_locations: list[str] | None = None
    property_type_interest: str | None = None
    buyer_type: str | None = None
    lead_score: int | None = None
    stage: str | None = None
    # False for an imported number nobody has qualified yet. Drives whether the
    # "mark as a lead" control is offered when logging a call.
    is_lead: bool = True
    batch_id: int | None = None
    # Staff working this lead in addition to its owner. Empty for most leads.
    assignees: list[Assignee] = Field(default_factory=list)
    owner_id: int | None = None
    owner_name: str | None = None
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime | None = None


class DuplicateCandidate(BaseModel):
    id: int
    name: str
    phone_last4: str | None = None
    match: Literal["phone_exact", "name_fuzzy"]
    score: int
    owner_name: str | None = None
    stage: str | None = None


class ReassignRequest(BaseModel):
    new_owner_id: int
    reason: str | None = None


# ---------------------------------------------------------------------------
# Bulk lead import (Excel / CSV -> cold caller queues)
# ---------------------------------------------------------------------------


class ImportRowPreview(BaseModel):
    row_number: int
    name: str
    phone: str
    email: str | None = None
    location: str | None = None
    status: Literal["new", "duplicate", "invalid"]
    detail: str | None = None


class ImportPreview(BaseModel):
    """What the owner sees before committing an import.

    Deliberately a separate round trip from the import itself: these files come
    from portals and purchased lists with no agreed shape, so the owner should
    see which column was read as the phone number before 800 rows land in
    someone's queue.
    """

    filename: str
    sheet_name: str | None = None
    header_row: int | None = None
    detected_columns: dict[str, str]
    total_rows: int
    importable: int
    duplicates: int
    invalid: int
    warnings: list[str]
    sample: list[ImportRowPreview]


class ImportAssignment(BaseModel):
    user_id: int
    name: str
    assigned: int


class ImportResult(BaseModel):
    batch_id: int
    batch_name: str
    imported: int
    duplicates: int
    invalid: int
    assignments: list[ImportAssignment]


class BatchPerformance(BaseModel):
    """How one uploaded calling list is doing.

    The owner's question is whether a list was worth buying, so the headline is
    `leads` — people a caller judged worth keeping — over `called`, not over
    the size of the file. A list nobody has started on should not look like a
    list that failed, which is why the rates are null rather than zero when
    their denominator is empty.
    """

    id: int
    name: str
    source_filename: str | None
    uploaded_by: str | None
    created_at: datetime
    archived_at: datetime | None

    # As delivered, before dedup — how dirty the file itself was.
    total_rows: int
    duplicate_rows: int
    invalid_rows: int

    # Live counts, recomputed on read: numbers get called and flagged after the
    # import, so nothing here can be frozen at upload time.
    size: int
    called: int
    uncalled: int
    reached: int
    leads: int
    showings: int
    closed: int

    contact_rate: float | None
    reach_rate: float | None
    conversion_rate: float | None

    assigned_to: list[str]
    last_activity_at: datetime | None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class PropertyBase(BaseModel):
    title: str | None = None
    location: str
    building: str | None = None
    property_type: Literal["apartment", "villa", "plot", "commercial"] | None = None
    listing_type: Literal["rent", "outright"]
    price: Decimal | None = None
    status: Literal["available", "blocked", "sold"] | None = "available"


class PropertyCreate(PropertyBase):
    pass


class PropertyUpdate(BaseModel):
    title: str | None = None
    location: str | None = None
    building: str | None = None
    property_type: str | None = None
    listing_type: str | None = None
    price: Decimal | None = None
    status: str | None = None


class PropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    location: str
    building: str | None = None
    property_type: str | None = None
    listing_type: str
    price: Decimal | None = None
    status: str | None = None
    source: str | None = None
    posted_by_agent_id: int | None = None
    posted_by_name: str | None = None
    created_at: datetime
    showing_count: int | None = None

    # Phase 3. Present on WhatsApp-sourced listings, null on manual ones.
    bhk: int | None = None
    area_sqft: int | None = None
    furnishing: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    source_group: str | None = None
    raw_message: str | None = None
    extraction_confidence: float | None = None
    review_state: str | None = None
    last_seen_at: datetime | None = None
    # How many times this listing has been seen across all monitored groups.
    # 1 means "posted once"; a high number means many brokers are pushing it.
    sighting_count: int | None = None


class PropertyMatch(BaseModel):
    """A suggested listing for a lead, with its reasons.

    The reasons are part of the contract, not decoration: an agent who cannot
    see why a flat was suggested will not trust the suggestions enough to use
    them, and an opaque score is indistinguishable from a random one.
    """

    property: PropertyOut
    score: float
    reasons: list[str]


# ---------------------------------------------------------------------------
# Property interests ("who showed what to whom")
# ---------------------------------------------------------------------------


class PropertyInterestCreate(BaseModel):
    contact_id: int
    property_id: int
    interest_level: Literal[
        "inquired", "site_visit_scheduled", "site_visit_done", "negotiating"
    ]
    note: str | None = None
    shown_at: datetime | None = None
    # shown_by_agent_id is intentionally absent: API_SPEC.md requires it to come
    # from the auth context, never from the client.


class PropertyInterestOut(BaseModel):
    contact_id: int
    contact_name: str | None = None
    property_id: int
    property_title: str | None = None
    property_location: str | None = None
    shown_by_agent_id: int | None = None
    shown_by_name: str | None = None
    interest_level: str | None = None
    shown_at: datetime


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


class CallCreate(BaseModel):
    contact_id: int
    outcome: Literal[
        "connected",
        "not_reachable",
        "not_interested",
        "interested",
        "callback_requested",
        "wrong_number",
    ]
    temperature: Literal["hot", "warm", "cold"] | None = None
    notes: str | None = None
    flagged_for_owner: bool = False
    # Promotes an imported number into the leads pipeline. Only a person who
    # has actually spoken to someone can judge this, so it is never inferred
    # from the outcome — "interested" on a cold call is often just politeness.
    marked_lead: bool = False
    follow_up_at: datetime | None = None


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: int | None = None
    contact_name: str | None = None
    caller_id: int
    caller_name: str | None = None
    outcome: str
    temperature: str | None = None
    notes: str | None = None
    flagged_for_owner: bool | None = None
    follow_up_at: datetime | None = None
    created_at: datetime


class CallCreateResponse(BaseModel):
    call: CallOut
    follow_up_task: "TaskOut | None" = None


class QueueContact(BaseModel):
    """The only client data a call queue carries: who to ring, and on what number.

    Deliberately not ``ContactOut``. Budget, preferred locations, stage and
    lead score are not needed to place a call, and a queue that returns them
    hands a caller the firm's book a page at a time. Narrowing the *response*
    rather than hiding fields in the UI means the extra data never leaves the
    server — the same reasoning as the phone masking in app/serializers.py.
    """

    id: int
    first_name: str
    last_name: str | None = None
    phone: str | None = None


class QueueItem(BaseModel):
    contact: QueueContact
    # Why this lead surfaced now. Operational, not client data — without it the
    # queue's order looks arbitrary and the caller cannot tell an overdue
    # promise from a routine touch.
    reason: str
    priority: int
    due_at: datetime | None = None


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


class ActivityCreate(BaseModel):
    contact_id: int | None = None
    property_id: int | None = None
    type: Literal["site_visit", "note", "stage_change", "follow_up"]
    body: str | None = None
    occurred_at: datetime | None = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: int | None = None
    contact_name: str | None = None
    property_id: int | None = None
    property_title: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    type: str
    body: str | None = None
    occurred_at: datetime


class FeedItem(BaseModel):
    """One entry in the owner's live activity feed.

    Calls, showings and activities are separate tables by design; the feed
    merges them into a single chronological stream so the owner reads one
    timeline rather than three.
    """

    kind: Literal["call", "activity", "showing"]
    occurred_at: datetime
    user_id: int | None = None
    user_name: str | None = None
    contact_id: int | None = None
    contact_name: str | None = None
    property_id: int | None = None
    property_title: str | None = None
    title: str
    detail: str | None = None
    tone: Literal["neutral", "positive", "warning", "signal"] = "neutral"
    outcome: str | None = None
    temperature: str | None = None
    flagged: bool = False


# ---------------------------------------------------------------------------
# Tasks (follow-ups)
# ---------------------------------------------------------------------------


class TaskCreateRequest(BaseModel):
    contact_id: int | None = None
    title: str
    due_at: datetime | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: int | None = None
    contact_name: str | None = None
    assigned_to: int
    assigned_to_name: str | None = None
    title: str
    due_at: datetime | None = None
    status: str
    source_call_log_id: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class TaskUpdateRequest(BaseModel):
    status: Literal["pending", "done", "cancelled"] | None = None
    due_at: datetime | None = None
    title: str | None = None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str | None = None
    action: str
    resource_type: str
    resource_id: int | None = None
    detail: dict[str, Any] | None = None
    occurred_at: datetime


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------


class PushSubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class PushConfig(BaseModel):
    enabled: bool
    public_key: str | None = None


# ---------------------------------------------------------------------------
# WhatsApp ingestion (Phase 3)
# ---------------------------------------------------------------------------


class WhatsAppGroupCreate(BaseModel):
    group_jid: str = Field(
        description="WhatsApp's own group id, ending in '@g.us'."
    )
    name: str
    note: str | None = Field(
        default=None,
        description=(
            "Optional context passed to the extractor, e.g. 'Andheri West "
            "rentals only'. Helps on terse messages."
        ),
    )
    is_active: bool = True


class WhatsAppGroupUpdate(BaseModel):
    name: str | None = None
    note: str | None = None
    is_active: bool | None = None


class WhatsAppGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_jid: str
    name: str
    note: str | None = None
    is_active: bool
    created_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0
    listing_count: int = 0
    pending_count: int | None = None


class IngestMessage(BaseModel):
    """One message as the gateway forwards it."""

    wa_message_id: str
    group_jid: str
    body: str
    sender_jid: str | None = None
    sender_name: str | None = None
    sent_at: datetime | None = None


class IngestRequest(BaseModel):
    messages: list[IngestMessage] = Field(max_length=200)


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int = Field(
        description="Already-seen wa_message_ids, ignored. Expected after a gateway reconnect."
    )
    unknown_groups: list[str] = Field(
        default_factory=list,
        description="group_jids not configured or inactive; their messages were dropped.",
    )


class WhatsAppMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    group_name: str | None = None
    sender_name: str | None = None
    body: str
    sent_at: datetime | None = None
    received_at: datetime
    status: str
    attempts: int
    error: str | None = None
    listings_found: int = 0
    listings_new: int = 0
    processed_at: datetime | None = None


class PropertySourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    message_id: int | None = None
    group_name: str | None = None
    posted_by_name: str | None = None
    posted_by_phone: str | None = None
    raw_message: str | None = None
    relation: str
    match_score: float | None = None
    seen_at: datetime


class IngestionStatus(BaseModel):
    """Owner-facing health view of the feed (API_SPEC: /whatsapp/ingestion-status)."""

    groups_active: int
    groups_total: int
    pending: int
    processing: int
    failed_last_24h: int
    messages_last_24h: int
    listings_last_24h: int
    properties_from_whatsapp: int
    duplicates_merged: int
    needs_review: int
    last_message_at: datetime | None = None
    last_processed_at: datetime | None = None
    extraction_configured: bool = Field(
        description="False when no Anthropic credentials are set; the queue will back up."
    )


class PropertyReviewRequest(BaseModel):
    review_state: Literal["confirmed", "rejected"]


# ---------------------------------------------------------------------------
# Generic list envelope
# ---------------------------------------------------------------------------


class Paged[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
    has_more: bool


CallCreateResponse.model_rebuild()
