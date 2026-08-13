# Tech Stack — Real Estate Broker CRM

## Summary

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind, built as a PWA | One codebase, mobile-first responsive, installable to home screen, push notifications via service worker, no App Store approval cycle |
| Backend | FastAPI (Python) | Async-friendly, fast to build REST APIs, good fit for the LLM-extraction and WhatsApp-ingestion background jobs |
| Database | PostgreSQL | Relational integrity for leads/deals/roles; JSONB columns where flexible fields are needed (e.g. audit log detail, WhatsApp raw message) |
| Auth | JWT-based sessions, role claim embedded in token | Simple, works well with RBAC middleware in FastAPI |
| Background jobs | A task queue (e.g. Celery or an async job runner) for WhatsApp ingestion, LLM parsing, lead scoring/routing | These are all async, retryable, potentially slow operations — must not block request/response cycle |
| WhatsApp ingestion | Unofficial WhatsApp Web automation gateway (e.g. Baileys-based) as a separate service, forwarding messages to the backend via an internal API/webhook | See `references/real_estate_domain.md` in the crm-leadgen-builder skill for the caveats (not official Business API) |
| Notifications | Web Push API (PWA push notifications) + optionally WhatsApp Business API for outbound messages | Push works natively with the PWA approach without needing a native app |
| Hosting | Any standard cloud (e.g. a VPS or managed Postgres + a container host) | No special requirements beyond running FastAPI + Postgres + Next.js; keep infra simple for a small-team internal tool |

## Why PWA over React Native (explicit rationale)

- **One codebase**: Next.js already fits your existing stack (used in the `crm-leadgen-builder` skill and prior projects) — no second frontend to maintain.
- **Faster iteration with Claude Code**: fewer moving parts (no native build pipeline, no App Store review) means faster ship cycles while features are still being validated with the actual brokerage staff.
- **Good-enough offline**: service workers can cache recently-viewed leads/properties for spotty-connectivity field use; full offline-first sync (writing while offline) can be added later if it proves necessary.
- **Upgrade path preserved**: if the team outgrows PWA (e.g. needs deep native integrations like background location or richer offline write support), the FastAPI backend and data model don't need to change — only the frontend layer would be rebuilt in React Native.

## Key libraries/services to plan for

- LLM API (Groq — `llama-3.3-70b-versatile` by default) for parsing unstructured WhatsApp property messages into structured fields — this is a genuine LLM extraction task, not a regex job, given how inconsistent listing formats are. Groq is chosen for throughput and price: a busy brokerage generates thousands of messages a day, and the task is structured copying out of messy text rather than reasoning, which does not need a frontier model. The trade is that Groq has no prompt caching, so the large system prompt is re-paid on every request and batching is what amortises it.
- A string-similarity library (e.g. `rapidfuzz`) for dedup logic (contacts and property listings).
- `python-jose` or similar for JWT handling in FastAPI.
- A Postgres migration tool (e.g. Alembic) from day one, since the schema will evolve across phases.
