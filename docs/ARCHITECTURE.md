# Architecture — Real Estate Broker CRM

## System overview

```
                    ┌─────────────────────┐
                    │   Next.js PWA        │  (mobile-first UI, installable,
                    │   (frontend)         │   push notifications)
                    └──────────┬───────────┘
                               │ REST (JSON, JWT auth)
                    ┌──────────▼───────────┐
                    │   FastAPI backend     │  (RBAC middleware, business logic)
                    └──┬────────┬────────┬──┘
                       │        │        │
             ┌─────────▼─┐  ┌───▼────┐ ┌─▼──────────────┐
             │ PostgreSQL │  │  Task  │ │  Audit log      │
             │  (primary  │  │ queue  │ │  (append-only,  │
             │   store)   │  │(async  │ │  written by     │
             │            │  │ jobs)  │ │  middleware on  │
             └────────────┘  └───┬────┘ │  every request) │
                                  │      └─────────────────┘
                       ┌──────────┼───────────────┐
                       │          │               │
              ┌────────▼──┐  ┌────▼─────┐  ┌──────▼───────┐
              │ WhatsApp   │  │ Lead     │  │ Scoring &    │
              │ ingestion  │  │ dedupe & │  │ routing      │
              │ gateway    │  │ property │  │ engine       │
              │ (separate  │  │ dedupe   │  │              │
              │ service)   │  │          │  │              │
              └────────────┘  └──────────┘  └──────────────┘
```

## Components

### 1. Frontend — Next.js PWA
- Role-aware routing: Owner/Manager/Agent/Cold-Caller each land on a different home dashboard (see `DESIGN_RULES.md`).
- Service worker for offline caching of recently-viewed leads/properties and for push notifications.
- All list views (leads, properties, activity feed) support filtering — this is a read-heavy app, filters are core UX, not an afterthought.

### 2. Backend — FastAPI
- **RBAC middleware**: every request resolves the caller's role and scopes queries accordingly (Agent never receives a query result outside their assigned leads, enforced at the query layer, not just hidden in the UI).
- **Audit middleware**: wraps every read/write on sensitive resources (contacts, exports) and writes an audit log entry — this must be structural (middleware-level), not something each endpoint has to remember to call, or it will be missed somewhere.
- **Export endpoint**: the only endpoints capable of returning bulk contact data are gated to Owner/Manager roles and themselves logged.

### 3. Database — PostgreSQL
- Full schema in `DATA_MODEL.md`. Key structural decisions:
  - Soft delete everywhere (`deleted_at`), never hard delete — audit trail must survive record deletion.
  - Every "interaction" (call, site visit, remark) is its own row in an `activities`/`call_logs` table, not a mutable field on the lead — this is what makes both the owner's activity feed and the audit trail possible.

### 4. Task queue (async jobs)
Runs anything that's slow, external, or retryable, off the request/response path:
- WhatsApp message → LLM parsing → structured property record
- Lead/property dedup checks
- Lead scoring recomputation
- Lead routing decisions
- Stale-lead alert generation

### 5. WhatsApp ingestion gateway
A separate small service (not inside the main FastAPI app) that maintains the WhatsApp connection and forwards new messages from configured groups to an internal FastAPI webhook endpoint. Kept separate because:
- It has a different failure mode (WhatsApp session drops, rate limits) than the main API and shouldn't be able to take down core CRM functionality if it breaks.
- It's the one component built on an unofficial integration (see `TECH_STACK.md`) — isolating it limits the blast radius of that risk.

### 6. Scoring & routing engine
Runs as a background job triggered on lead creation/update. Follows the layered approach from the `crm-leadgen-builder` skill: score first (budget fit, site-visit signal, recency), then route (territory → project match → urgency → workload balance → fallback owner). Every routing decision is logged (see `SECURITY_MODEL.md` — this doubles as an audit record).

## Data flow: WhatsApp listing → searchable inventory (end to end)

1. Message posted in a monitored WhatsApp group.
2. Ingestion gateway receives it, forwards raw text + metadata to `/internal/whatsapp/ingest`.
3. Job queued: LLM extraction → structured fields (location, building, BHK, rent/sale, price).
4. Dedup check against existing `properties` records (building + BHK + price similarity).
5. If new: insert into `properties` with `source = whatsapp_group`, `raw_message` retained.
6. If likely duplicate: attach as an additional source reference rather than creating a new row.
7. Now queryable/filterable in the unified inventory view by any staff with inventory-view permission.

## Data flow: cold call → owner visibility (end to end)

1. Cold caller opens their queue, places a call, logs outcome via the remark form.
2. `POST /calls` writes the call log row (own entity, not a field update).
3. Audit middleware logs the write.
4. If outcome qualifies (e.g. "Callback Requested"), a follow-up task is auto-created.
5. If flagged for owner attention, an entry is written to the owner's escalation inbox and a push notification is sent.
6. The owner's live activity feed reads directly from the same `activities`/`call_logs` table — no separate reporting pipeline needed, which keeps "what the owner sees" always in sync with "what actually happened."
