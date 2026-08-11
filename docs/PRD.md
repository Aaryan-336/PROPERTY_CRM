# Product Requirements Document — Real Estate Broker CRM

## 1. Problem statement

A small real estate brokerage (an owner + staff: closing agents and a cold-calling team) currently runs on WhatsApp, phone calls, and scattered notes. This causes three concrete problems:
1. **No unified view of inventory** — property listings are scattered across hundreds of WhatsApp groups; agents can't quickly find matching inventory for a client.
2. **No owner visibility** — the owner doesn't know which agent is showing which property to which client, or whether leads are being followed up.
3. **Data leakage risk** — agents can walk away with the firm's client list, since there's no access control or audit trail today.

## 2. Goals

- Give every agent a fast, mobile-first workflow for managing their leads, site visits, and calls.
- Give the owner full, real-time visibility into what every staff member is doing with every client and property — without slowing staff down.
- Prevent staff from extracting or exfiltrating the client/lead database.
- Aggregate property inventory from WhatsApp groups into one searchable, segmented view.
- Support a dedicated cold-calling workflow with fast remark logging and automatic follow-up/escalation.

## 3. Non-goals (for this phase)

- Native mobile app (React Native) — PWA only, see `TECH_STACK.md` for rationale.
- Payment/commission processing.
- Public-facing property listing website (this is an internal tool for the brokerage, not a buyer-facing portal).
- Legal/document e-signing workflows.

## 4. Users & roles

| Role | Who | Core need |
|---|---|---|
| Owner | Firm head | See everything, every agent, every lead, every property, real-time |
| Manager | Senior staff (optional, phase 2) | Oversee a sub-team, same visibility scoped to their team |
| Agent | Closing/field agents | Manage their assigned leads, log site visits, view matched inventory |
| Cold Caller | Calling team | Work a call queue, log remarks fast, escalate hot leads |

Full permission detail lives in `ROLES_PERMISSIONS.md`.

## 5. Core user stories

- As the **Owner**, I want a live feed of every call, site visit, and status change across the firm, so I always know what's happening without asking staff.
- As the **Owner**, I want to see exactly which agent showed which property to which client and when, so I can resolve disputes and spot underperformance.
- As the **Owner**, I want staff unable to export or bulk-download the client list, so the firm's data can't walk out the door with an agent.
- As an **Agent**, I want to log a site visit or call in under 15 seconds from my phone, standing in the field, so logging doesn't get skipped.
- As an **Agent**, I want the system to suggest matching properties for a client's stated budget/location, so I don't manually cross-reference listings.
- As a **Cold Caller**, I want a prioritized queue and a fast dropdown+notes form for call outcomes, so I can get through a high volume of calls per day.
- As a **Cold Caller**, I want to flag a hot lead for the owner's attention with one tap, so it doesn't sit in my queue waiting for my own follow-up.
- As anyone entering listings, I want property data pulled automatically from our WhatsApp groups, so I'm not manually re-typing thousands of listings.

## 6. Success metrics (informal, for a small-team internal tool)

- % of site visits/calls logged within the same day they happen (target: near 100%, since this is the core anti-leakage and visibility mechanism).
- Owner can answer "who showed Property X to Client Y" without asking staff, 100% of the time.
- Time-to-log a call or site visit: under 15 seconds on mobile.
- Zero successful bulk exports of the client database by non-Owner roles.

## 7. Related documents

`FEATURE_LIST.md` (full feature breakdown), `ARCHITECTURE.md`, `TECH_STACK.md`, `DESIGN_RULES.md`, `PHASES.md`, `DATA_MODEL.md`, `SECURITY_MODEL.md`, `ROLES_PERMISSIONS.md`, `API_SPEC.md`.
