# Security Model — Real Estate Broker CRM

This is the highest-priority document in this set — the owner's stated #1 concern was preventing staff from stealing client data while keeping himself fully informed. Every rule here should be enforced at the API/query layer, never only hidden in the UI (a hidden button is not a security control — a determined staff member can call the API directly).

## Threat model

The realistic threat here isn't an external hacker — it's an **insider with legitimate login access** trying to extract the client/lead list (e.g. before leaving to join a competitor, or to freelance on the side). Design against that specific threat:
- An agent copying the visible contact list manually, screen by screen → mitigate with pagination + rate limiting + masked numbers, not solvable perfectly but raise the cost.
- An agent using the API/export endpoint to bulk-download data → mitigate by removing that capability from their role entirely.
- An agent's account being used after they've left → mitigate with prompt deactivation and session invalidation.
- An agent quietly claiming leads and going dark on logging → mitigate with mandatory activity logging tied to lead ownership, visible to the owner.

## Access control principles

1. **Enforce scoping in the query layer, not just the UI.** Every list/detail endpoint for contacts, properties, and activities filters by the caller's role and ownership at the SQL/ORM level. An Agent's `GET /contacts` query has `WHERE owner_id = current_user.id` baked into the query construction — never "fetch all, filter in the frontend."
2. **No bulk export capability for Agent or Cold Caller roles**, at the API level — the endpoint simply doesn't authorize their role, not "hidden from their UI but technically reachable."
3. **Owner and Manager can export**, but every export call is logged to `audit_log` with `action = 'export'` and a `detail` count of rows exported — so even authorized exports are traceable if the data later leaks.
4. **Pagination is mandatory and capped** on all list endpoints (e.g. max 50 records per page) — this limits how much data any single request can return, making manual scraping slower and more visible (many rapid paginated requests is itself a detectable pattern).

## Contact masking

- `contacts.phone_masked = true` by default for newly assigned leads until the agent has logged a qualifying interaction (e.g. first call) — reduces the value of grabbing a lead list before doing any real work on it.
- Full phone/email is always visible to Owner and Manager.
- Masking logic lives in API response serialization (see `DATA_MODEL.md` notes) — the raw value should not even be sent to the client for a masked contact, not just visually hidden by CSS, since a network inspector would defeat CSS-only masking.

## Audit logging

- **Structural, not opt-in**: implemented as FastAPI middleware wrapping all requests touching `contacts`, `properties`, `call_logs`, and any export endpoint — individual endpoint handlers don't need to remember to log, so nothing gets missed.
- Logged fields: `user_id`, `action`, `resource_type`, `resource_id`, `detail` (JSONB — e.g. which fields changed, how many rows exported), `occurred_at`.
- **Append-only at the database level where possible** — revoke UPDATE/DELETE grants on `audit_log` for the application's DB role, so even a compromised or malicious use of the app's own credentials can't tamper with history.
- Retained indefinitely (or per a retention policy the owner sets) — audit value degrades if logs are purged too aggressively.

## Lead reassignment control (Phase 2)

- Reassigning a lead's `owner_id` to a different agent requires an Owner/Manager-approved action, not a self-service agent action — prevents an agent quietly "trading" leads with a colleague to obscure who's actually working what.
- Every reassignment is itself an audit log entry with old/new owner recorded.

## Session & device controls (Phase 3)

- **Sliding sessions with an absolute cap**, rather than one fixed expiry.
  A single lifetime forced a choice between "signs you out mid-afternoon" and
  "never expires", and the 12h setting this replaces picked the first — which in
  practice trained everyone to re-enter a password on any hiccup, the habit
  phishing depends on. Two independent numbers instead:
  - `SESSION_IDLE_DAYS` (default 30) — the token's own life, renewed whenever
    the app is used, so it measures *silence*, not elapsed time.
  - `SESSION_ABSOLUTE_DAYS` (default 90) — measured from the moment the password
    was typed and **never** extended, so no amount of use makes a session
    permanent. `sessions.chain_started_at` carries it across renewals.

  Renewal is `POST /auth/refresh`. It runs behind the ordinary auth dependency,
  so it can only extend a session that is already live — it can never revive a
  revoked one, and therefore cannot be used to undo a logout, a password change
  or a deactivation. A renewed token supersedes its predecessor within
  `RENEWAL_GRACE_SECONDS` (60), which covers requests already in flight without
  leaving the old token useful.

  Shorten both on a shared device. On a lost phone, deactivating the user or
  changing the password still kills every session immediately.
- Optional: cap concurrent sessions per user, so a shared/leaked credential can't be used from many devices simultaneously without at least logging the anomaly.
- Immediate session invalidation on account deactivation (when staff leave) — deactivating a `users` row should invalidate any outstanding tokens, not just block new logins.

## What this model deliberately does NOT attempt

Being honest about limits matters more than implying perfect security:
- It cannot stop an agent from **memorizing or manually writing down** a small number of contacts they're actively working — no software control fully prevents this, and treating it as solvable would be misleading. The realistic goal is raising the cost/visibility of large-scale extraction, not making leakage physically impossible.
- It does not include device-level MDM (mobile device management) or preventing screenshots — those are heavier-weight controls a small brokerage likely won't want the operational overhead of; flag as a possible Phase 4+ discussion if it becomes a real problem in practice.
