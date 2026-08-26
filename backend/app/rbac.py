"""Endpoint-level authorization, straight from the ROLES_PERMISSIONS.md matrix.

This is the second of two independent layers. ``app/scoping.py`` decides which
*rows* a caller can see; this decides which *capabilities* a role has at all.
Bulk export is the clearest case: for an Agent the export endpoint does not
authorize, rather than returning an empty or filtered file -- SECURITY_MODEL.md
§2 asks for the capability to be absent from the role, not hidden from the UI.
"""

from __future__ import annotations

from app.errors import forbidden
from app.models import ROLE_AGENT, ROLE_COLD_CALLER, ROLE_OWNER
from app.scoping import Principal

# Capability -> roles that hold it. Phase 1 roles only; Manager arrives in
# Phase 2 with team-scoped variants of the Owner rows.
CAPABILITIES: dict[str, frozenset[str]] = {
    # Browsing the lead book, and browsing inventory, are both withheld from
    # Cold Callers. They work a queue: one client at a time, name and number
    # only. A caller who can page through the whole lead list or the firm's
    # inventory can copy either, and neither is needed to make a call — which
    # makes the access pure downside under SECURITY_MODEL.md's threat model
    # (people who already have legitimate accounts).
    #
    # This is a capability, not a UI conditional, so hiding the nav is not what
    # enforces it: the list endpoints refuse the role outright.
    "contacts.browse": frozenset({ROLE_OWNER, ROLE_AGENT}),
    "properties.read": frozenset({ROLE_OWNER, ROLE_AGENT}),
    "contacts.create": frozenset({ROLE_OWNER, ROLE_AGENT, ROLE_COLD_CALLER}),
    "contacts.edit": frozenset({ROLE_OWNER, ROLE_AGENT, ROLE_COLD_CALLER}),
    "contacts.delete": frozenset({ROLE_OWNER}),
    "contacts.export": frozenset({ROLE_OWNER}),
    "contacts.bulk_import": frozenset({ROLE_OWNER}),
    "contacts.reassign": frozenset({ROLE_OWNER}),
    "properties.write": frozenset({ROLE_OWNER, ROLE_AGENT}),
    # Narrower than properties.write, and deliberately so. Agents add and
    # correct listings all day; removing one is different in kind. Inventory
    # arrives automatically from the feed and is shared by the whole firm, so a
    # deletion is not "my mistake, my row" -- it takes a flat out of everyone's
    # search, including the sourcing history behind it. Same reasoning as
    # contacts.delete, which has always been Owner-only.
    "properties.delete": frozenset({ROLE_OWNER}),
    "property_interests.write": frozenset({ROLE_OWNER, ROLE_AGENT}),
    "property_interests.read": frozenset({ROLE_OWNER, ROLE_AGENT}),
    "calls.log": frozenset({ROLE_OWNER, ROLE_AGENT, ROLE_COLD_CALLER}),
    "escalations.receive": frozenset({ROLE_OWNER}),
    "feed.firmwide": frozenset({ROLE_OWNER}),
    "audit.read": frozenset({ROLE_OWNER}),
    "users.manage": frozenset({ROLE_OWNER}),
    # ROLES_PERMISSIONS.md: "Configure WhatsApp ingestion groups -- Owner only".
    # Covers the monitoring and review surface too, not just group CRUD: which
    # groups the firm sources from is competitive information, and the raw feed
    # carries counterparty numbers the firm never chose to publish.
    "whatsapp.manage": frozenset({ROLE_OWNER}),
}

# Fields a Cold Caller may change on a contact. Per ROLES_PERMISSIONS.md they
# log remarks and move temperature/follow-up, but never budget, location
# preferences, or ownership.
COLD_CALLER_WRITABLE_CONTACT_FIELDS = frozenset(
    {"stage", "lead_source", "campaign", "buyer_type"}
)

# Ownership is never self-service for anyone below Owner: an agent quietly
# reassigning leads to themselves is exactly the behaviour the audit trail
# exists to prevent.
OWNER_ONLY_CONTACT_FIELDS = frozenset({"owner_id", "phone_masked", "lead_score"})


def has(principal: Principal, capability: str) -> bool:
    allowed = CAPABILITIES.get(capability)
    if allowed is None:
        raise KeyError(f"Unknown capability {capability!r}")
    return principal.role in allowed


def assert_capability(principal: Principal, capability: str) -> None:
    if not has(principal, capability):
        raise forbidden(
            f"Role '{principal.role}' does not have the '{capability}' capability."
        )


def assert_contact_fields_writable(principal: Principal, fields: set[str]) -> None:
    """Reject field-level writes the caller's role may not perform."""
    if principal.is_owner:
        return

    blocked = fields & OWNER_ONLY_CONTACT_FIELDS
    if blocked:
        raise forbidden(
            "Only the Owner can change: " + ", ".join(sorted(blocked)) + "."
        )

    if principal.role == ROLE_COLD_CALLER:
        not_allowed = fields - COLD_CALLER_WRITABLE_CONTACT_FIELDS
        if not_allowed:
            raise forbidden(
                "Cold Callers may update "
                + ", ".join(sorted(COLD_CALLER_WRITABLE_CONTACT_FIELDS))
                + " and log call remarks, but not: "
                + ", ".join(sorted(not_allowed))
                + "."
            )
