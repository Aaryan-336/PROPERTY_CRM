# Feature List — Real Estate Broker CRM

Organized by module. Each feature is tagged with the phase it belongs to (see `PHASES.md`) — [P1] core, [P2] depth, [P3] advanced/automation.

## 1. Leads & Contacts
- [P1] Lead capture: manual entry, phone/WhatsApp, Instagram/Meta lead ads webhook
- [P1] Contact profile: budget range, preferred locations, property type interest, buyer type (end-user/investor), urgency
- [P1] Duplicate detection on phone number + fuzzy name match
- [P2] Lead source & campaign tracking (for cost-per-lead reporting)
- [P3] Auto lead scoring (budget fit, site-visit signal, response time — see `crm-leadgen-builder` skill's real-estate scoring model)
- [P3] Auto-routing of new leads to the right agent by territory/project

## 2. Property Inventory
- [P1] Property record: location, building/society, price, rent-vs-outright, status (available/blocked/sold)
- [P1] Filter/search by location, building, rent-vs-outright, price/budget band
- [P2] Property-to-client matching (suggest inventory matching a client's stated budget/location)
- [P2] Photos/media attached to listings
- [P3] **WhatsApp Property Feed Aggregator**: ingest listings posted in WhatsApp groups, LLM-extract structured fields (location, building, BHK, price, rent/sale), dedupe near-identical reposts, merge into the unified inventory with `source = whatsapp_group`

## 3. Site Visits & Pipeline
- [P1] Pipeline stages: New → Contacted → Site Visit Scheduled → Visited → Negotiating → Closed/Lost
- [P1] Site visit scheduling with reminders
- [P1] Every property-shown-to-client event logged as its own record (this is the backbone of owner visibility — see module 6)
- [P2] Calendar view of scheduled visits per agent

## 4. Communication Logging
- [P1] One-tap call logging (fastest action in the app)
- [P2] WhatsApp Business API integration for logging/sending messages from within the CRM
- [P1] Follow-up task/reminder per lead

## 5. Cold Calling Team Module
- [P1] Prioritized call queue scoped to the caller's assigned leads only
- [P1] Fast remark form: outcome dropdown (Connected / Not Reachable / Not Interested / Interested / Callback Requested / Wrong Number), temperature dropdown (Hot/Warm/Cold), free-text notes
- [P1] Auto follow-up task creation on qualifying outcomes (e.g. Callback Requested)
- [P1] One-tap escalation/flag to owner for hot leads or issues, landing in a separate owner inbox
- [P3] Hot leads flagged by cold-callers auto-reroute to a closing agent

## 6. Security & Anti-Leakage (see `SECURITY_MODEL.md` for full detail)
- [P1] Role-based access control (Owner / Manager / Agent / Cold Caller)
- [P1] No bulk export/download/print for Agent and Cold Caller roles
- [P1] Immutable audit log: every view, edit, export, status change — timestamped, attributed, retained after soft-delete
- [P2] Masked contact info (full phone/email hidden from staff until a lead is formally assigned)
- [P2] Lead reassignment requires Owner/Manager approval
- [P3] Session/device control: concurrent session limits, forced logout on anomaly

## 7. Owner Oversight & Reporting
- [P1] Live activity feed across the whole firm
- [P1] "Who showed what to whom" view — filterable by agent, property, or client
- [P2] Team performance dashboard: leads per agent, conversion rate, response time, visit-to-close ratio
- [P2] Stale lead alerts (no activity in N days)
- [P2] Owner inbox for cold-caller escalations
- [P3] Cost-per-lead / channel conversion reporting (ties to lead source tracking)

## 8. Platform / Cross-cutting
- [P1] Mobile-first responsive UI (PWA — installable, works offline for viewing recently-loaded data)
- [P1] Push notifications (follow-up reminders, owner escalations, stale-lead alerts)
- [P2] Role-based dashboards (each role sees a different home screen tuned to their workflow)
