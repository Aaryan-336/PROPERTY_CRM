# API Spec — Real Estate Broker CRM

Base: REST, JSON, JWT bearer auth. Every endpoint below is subject to the role scoping in `ROLES_PERMISSIONS.md` — this doc lists the surface area, not the per-role query filters (those live in `SECURITY_MODEL.md`).

## Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | Returns JWT with embedded role claim |
| POST | `/auth/change-password` | Change your own. Requires the current password — being signed in is not enough. Revokes every session and returns a freshly issued token so the caller stays signed in and everyone else does not. |
| POST | `/users/{id}/reset-password` | Owner only. For staff who have lost theirs; there is no email on this system and so no reset link. Generates one if none supplied, and never echoes one that was. Refuses any Owner, including the caller, so it cannot be used to skip the current-password check. |
| POST | `/auth/logout` | Invalidates session/token |

## Users (Owner only, mostly)

| Method | Path | Notes |
|---|---|---|
| GET | `/users` | Owner: all; Manager: own team |
| POST | `/users` | Owner only — create staff account |
| PATCH | `/users/{id}` | Update role, manager_id, is_available, or deactivate |
| GET | `/team/performance?days=30` | Owner only — per-person calls (broken down by outcome), connect rate, showings, leads by stage, conversion rate, open/overdue follow-ups, and median hours from lead arrival to first call. Grouped aggregates, so cost does not scale with headcount. |
| GET | `/users/workload` | Owner only — every staff member with live leads, open/overdue follow-ups, calls and showings in the last 7 days. Powers the team screen so "remove this person" is an informed decision. |
| POST | `/users/{id}/reassign-leads` | Owner only — move every live lead to another active staff member. Closed/lost leads stay put. Audited as `reassign`, and each move writes an activity row on the lead. |

## Contacts / Leads

| Method | Path | Notes |
|---|---|---|
| GET | `/contacts` | Paginated (max 50/page), filterable by stage/owner/source/score. Query-scoped by role. Excludes imported numbers nobody has flagged as a lead — `include_targets=true` includes them, `batch_id` narrows to one database. |
| POST | `/contacts` | Create; triggers dedup check |
| GET | `/contacts/{id}` | Full detail; phone/email masked per role + `phone_masked` state |
| PATCH | `/contacts/{id}` | Update fields; audit-logged |
| DELETE | `/contacts/{id}` | Soft delete only (Owner/Manager) |
| POST | `/contacts/{id}/reassign` | Owner/Manager only; requires approval, audit-logged with old/new owner |
| POST | `/contacts/bulk-import/preview` | Owner only — parse an Excel/CSV calling list and report what would happen, writing nothing. Detects the header row under title rows, maps columns by alias, and falls back to value-sniffing when headers are unrecognised or absent. |
| GET | `/lead-batches` | Owner only — every uploaded calling list with live conversion numbers: size, called, reached, leads produced, and rates. Rates are `null`, not 0, when the denominator is empty. |
| GET | `/lead-batches/{id}` | One database's performance. |
| GET | `/contacts/{id}/assignees` | Staff working this lead besides its owner. Scoped like any other read. |
| PUT | `/contacts/{id}/assignees` | Owner only. Body is the complete desired set, not a delta, so unticking removes. Each new assignee gets a follow-up Task and gains read access to that contact — see the widened predicate in `app/scoping.py`. Removing someone cancels their open task on it. |
| POST | `/contacts/bulk-import` | Owner only — import and assign. `assign_to` accepts several staff ids and deals rows round-robin. Setting `owner_id` is what places a lead in that person's `/call-queue`. Existing leads are skipped via the contact dedup in `app/dedup.py`. Audited with counts and recipients. |
| GET | `/contacts/export` | Owner/Manager only; audit-logged with row count |

## Properties

| Method | Path | Notes |
|---|---|---|
| GET | `/properties` | Filterable by location, building, listing_type (rent/outright), price range |
| POST | `/properties` | Manual listing creation |
| GET | `/properties/{id}` | Detail, includes `property_interests` history |
| PATCH | `/properties/{id}` | Update status/price/etc. |
| GET | `/properties/{id}/matches` | Suggested matching contacts for this property (Phase 2, not yet built) |
| GET | `/contacts/{id}/matches` | **Built.** Suggested inventory for a lead, scored on preferred location, budget fit (10% headroom over `budget_max`), property type and freshness. Each result carries the reasons it matched — an unexplained ranking does not get used. |
| GET | `/properties/{id}/sources` | Provenance for a listing: every group/broker sighting, with the raw message. Readable by all roles. |
| POST | `/properties/{id}/review` | Owner only — confirm or reject a low-confidence extraction. Rejecting soft-deletes it. |

Property list filters also accept `bhk`, `source` (`manual` / `whatsapp_group`) and `review_state`.

## Property Interests (site-visit / shown-to tracking)

| Method | Path | Notes |
|---|---|---|
| POST | `/property-interests` | Log a "shown to" event: contact_id, property_id, interest_level; `shown_by_agent_id` set from auth context, not client-supplied |
| GET | `/property-interests?contact_id=&property_id=&agent_id=` | Powers the "who showed what to whom" view — filterable by any of the three |

## Call Logs (cold calling)

| Method | Path | Notes |
|---|---|---|
| GET | `/call-queue` | Cold caller's prioritized queue of assigned leads. Paged (`limit` ≤ 50, `offset`) and returns the true `total` — the per-request cap is the anti-scraping control, but a caller handed 300 imported leads must be able to see and work all of them. |
| POST | `/calls` | Log a call: contact_id, outcome, temperature, notes, flagged_for_owner |
| GET | `/calls?contact_id=` | Call history for a contact |
| GET | `/owner/escalations` | Owner inbox of flagged calls (Owner/Manager only) |

## Activities (site visits, notes, stage changes)

| Method | Path | Notes |
|---|---|---|
| POST | `/activities` | Generic activity log entry |
| GET | `/activities?contact_id=` | Activity timeline for a contact |
| GET | `/activities/feed` | Firm-wide (Owner) or team (Manager) live activity feed |

## Audit Log

| Method | Path | Notes |
|---|---|---|
| GET | `/audit-log` | Owner (full) / Manager (team) only; filterable by user, resource_type, action, date range |

## WhatsApp Ingestion (internal, Phase 3)

| Method | Path | Notes |
|---|---|---|
| POST | `/internal/whatsapp/ingest` | Called by the ingestion gateway, not the frontend. **HMAC-authenticated, not JWT** — the gateway is a machine with no user identity, and issuing it a staff credential would put a human role's token on the box running the unofficial WhatsApp integration. Signature is `HMAC-SHA256(secret, "<unix-ts>.<raw body>")` over `X-Balaji-Signature` / `X-Balaji-Timestamp`, with a 5-minute replay window. Stores messages verbatim; extraction is done by a worker, not inline. **Idempotent on `wa_message_id`** — the gateway replays its buffer after every reconnect. Returns 503 when no secret is configured (fails closed). |
| GET | `/internal/whatsapp/groups` | Same HMAC auth. Lets the gateway pull its watch list, so the owner's toggle in the CRM is the single source of truth. |
| GET | `/whatsapp/ingestion-status` | Owner only — groups connected, queue depth, failures in 24h, listings produced, reposts merged, and whether extraction credentials are configured at all. |
| GET | `/whatsapp/groups` · POST · PATCH · DELETE | Owner only — manage monitored groups. Removal is a soft delete so listings sourced from the group keep their provenance. |
| GET | `/whatsapp/messages` | Owner only — raw feed with per-message extraction state, for debugging a group producing nothing useful. |
| POST | `/whatsapp/reprocess/{id}` | Owner only — requeue a message. Raw bodies are stored before parsing precisely so a prompt fix can be replayed over history. |

## Lead Scoring & Routing (Phase 3)

| Method | Path | Notes |
|---|---|---|
| POST | `/leads/{id}/score` | Recompute score (also triggered automatically on relevant updates) |
| POST | `/leads/{id}/route` | Trigger routing decision; returns assigned agent + reasoning, audit-logged |

## Conventions

- All list endpoints: cursor or offset pagination, capped page size (see `SECURITY_MODEL.md` — this is a security control, not just a performance one).
- All timestamps in ISO 8601, UTC.
- Error responses: `{"error": {"code": "...", "message": "..."}}` — consistent shape so the frontend can handle errors generically.
- Every write endpoint that touches `contacts`, `properties`, or triggers an export is wrapped by the audit-logging middleware described in `SECURITY_MODEL.md` — this should not require per-endpoint opt-in.
