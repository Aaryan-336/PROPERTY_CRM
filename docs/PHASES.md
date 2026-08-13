# Build Phases — Real Estate Broker CRM

Phased so the owner's two core needs (security/audit, and visibility) are load-bearing from Phase 1, not bolted on later — retrofitting an audit trail onto a system that's already in daily use is much harder than building it in from day one.

## Phase 1 — Core CRM + Security Foundation + Cold Calling

Ship a usable, secure daily-driver first.

- Auth + RBAC (Owner / Agent / Cold Caller roles; Manager can wait for phase 2 if not immediately needed)
- Contacts/leads: manual entry, profile fields, duplicate detection
- Property inventory: manual entry, filter by location/building/rent-or-sale/price
- Pipeline stages + site visit logging (property-shown-to-client as its own record)
- One-tap call logging
- Cold calling module: queue, fast remark form, auto follow-up, owner escalation
- Immutable audit log (middleware-level, on every sensitive read/write)
- No bulk export for non-Owner roles
- Owner live activity feed + "who showed what to whom" view
- Mobile-first PWA shell with push notifications for follow-ups/escalations

**This phase alone solves the two problems the owner stated first**: staff can't quietly walk off with data, and the owner sees everything.

## Phase 2 — Depth & Team Management

- Manager role + team-scoped visibility
- Masked contact info for staff until lead assignment
- Lead reassignment approval flow
- Team performance dashboard (conversion rate, response time, visit-to-close ratio)
- Stale-lead alerts
- Property-to-client matching suggestions
- WhatsApp Business API integration for in-app messaging
- Photos/media on property listings
- Lead source & campaign tracking (Instagram/Meta lead ads ingestion)

## Phase 3 — Automation & Advanced Inventory

- ✅ **WhatsApp Property Feed Aggregator — built.** Ingestion gateway (`gateway/`, Baileys) → HMAC-signed webhook → raw message store → LLM extraction (Groq, JSON-schema structured outputs) → deterministic normalization → two-stage dedup → unified inventory, with an owner-facing monitoring and review console. See `ARCHITECTURE.md` for the data flow and `gateway/README.md` for the unofficial-integration caveats.
  - Note on "the WhatsApp API": there is no official API — paid or otherwise — that can read *group* messages. The Cloud API only delivers messages sent to a registered business number. Group ingestion necessarily means driving a real account over WhatsApp Web multi-device, which is what `TECH_STACK.md` already specified and what the gateway implements.
- Automated lead scoring (budget fit, site-visit signal, recency)
- Automated lead routing (territory/project match, workload balancing, hot-lead bypass)
- Cold-caller "Hot" flag auto-reroutes to a closing agent
- Session/device control (concurrent session limits, anomaly-triggered logout)
- Cost-per-lead / channel conversion reporting

## Sequencing rationale

- Security and owner-visibility features are in Phase 1, not treated as "polish" — they're the actual reason this project exists, per the stated requirements.
- The WhatsApp aggregator is powerful but technically riskier (unofficial integration, LLM parsing accuracy, high message volume) — it's sequenced last so a delay or hiccup there doesn't block the core CRM from being usable by staff.
- Automation (scoring/routing) comes after the manual workflow is proven — automating a workflow the team hasn't validated by hand risks automating the wrong thing.
