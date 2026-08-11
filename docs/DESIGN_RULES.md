# Design Rules — Real Estate Broker CRM

The brief already has a real answer to "what should this look like": not a generic white-card SaaS dashboard, but something with the confidence of the product mockups this was scoped against — bold dark surface cards, tactile status pills, checkpoint timelines, floating navigation. This doc pins that down as an actual token system, not a vibe, so Claude Code builds one coherent product instead of default Tailwind components.

Every screen is still judged against: "can a busy agent do this one-handed, in under 15 seconds, with one thumb?" — the identity below has to survive that test, not override it.

## Visual identity

### Color

| Token | Hex | Use |
|---|---|---|
| Ink | `#15141B` | Primary dark-surface cards (hero balance-style cards, nav, owner escalation inbox) — this is the "brand black," used deliberately, not `#000000` |
| Parchment | `#F6F2EA` | App background — warm, not sterile white |
| Card White | `#FFFFFF` | Secondary/light cards on top of Parchment |
| Sandstone | `#C9863E` | Primary accent — CTAs, active states, selected day/tab. Warm and architectural rather than a generic SaaS blue or the near-ubiquitous AI-default terracotta |
| Deep Teal | `#1E5C56` | Secondary accent — "verified," owner-visibility, trust-related states (audit log, owner-only badges) |
| Signal | `#D9482F` | Hot leads, owner escalations, urgent flags only — used sparingly so it stays meaningful |

Status colors (for pipeline stages, call outcomes) are never color-alone — always paired with a label, per the accessibility rule below.

### Type

- **Display** (headlines, section titles, the owner dashboard's big numbers): a confident geometric grotesk at bold weight, tight tracking — the kind of face that reads as architectural, not corporate-friendly. Think Neue Montreal / General Sans class, not Inter-at-700.
- **Body** (everything else — lists, forms, remarks): a warm, highly legible humanist sans at regular/medium weight — optimized for outdoor mobile readability over character.
- **Utility/mono** (tracking-style data — lead IDs, timestamps, prices, phone numbers): a monospaced or tabular-figure face, so numbers align in lists and price/budget figures scan quickly — directly inspired by the tracking-ID treatment in the shipping-app reference.

### Layout concept

- **Dark cards carry weight and trust.** The Ink surface is reserved for the things the owner most needs to trust: the day's summary/balance-style hero, the escalation inbox, audit-adjacent UI. Everything routine (a contact list, a property card) sits on Parchment/Card White. This gives the eye an instant read on "this matters" vs. "this is routine browsing," which a flat white-everywhere dashboard can't do.
- **Rounded, tactile cards** (20–28px radius), not sharp corporate rectangles — matches the reference mockups' softness without going full bubble/toy.
- **Floating pill bottom nav on mobile** (icons only, 4–5 items max), not a bar flush with the screen edge — reinforces the "considered product" feel over a default tab bar.
- **Avatar stacks** for anything collaborative or team-visible (e.g. "3 agents worked this lead this week," an escalation's participants) — small, circular, overlapping, exactly like the daily-challenge participant stack in the fitness reference.

### Signature element — the Journey Timeline

The one element this product should be remembered by: a **vertical checkpoint timeline** — a connected line of circular nodes, each with a check/status icon and a timestamp — reused everywhere something has a journey:
- A lead's pipeline stage progress (New → Contacted → Visited → Negotiating → Closed)
- A property's "shown to" history — who showed it, to whom, when (the owner's core visibility feature)
- A cold-call's outcome → follow-up → escalation chain

This is a deliberate borrow from the shipping-tracker reference's package-tracking timeline, and it's not just decorative here: it's the same underlying idea — "where is this thing right now, and who touched it" — applied to leads and property viewings instead of packages. That mapping is the product's actual differentiator (owner visibility), so the signature visual element and the core feature are the same thing, not decoration bolted onto a dashboard.

## Desktop / laptop view

Mobile is the primary target (field agents, cold callers), but the Owner realistically reviews the business from a laptop at day's end, and Agents will sometimes be at a desk. Don't ship a desktop layout that's just the mobile layout stretched wide — that's the single most common way these apps end up feeling unfinished.

- **Breakpoint strategy**: mobile up to ~768px is the design target described above; ≥1024px switches to the laptop layout below. 768–1024px (tablet) can inherit the laptop layout at reduced density rather than needing a third distinct design.
- **Navigation**: the floating pill bottom nav (mobile) becomes a **fixed left sidebar rail** on laptop — icon + label, Ink surface, same visual language as the mobile nav pill just reoriented. Frees the full viewport height for data-dense views instead of wasting a bottom bar on a screen with room to spare.
- **Owner dashboard is where desktop earns its keep**: multi-column layout — live activity feed, team performance snapshot, and escalation inbox as three panels side by side, instead of the stacked single-column mobile view. This is the view the owner is most likely to actually open on a laptop, so it should look like a real command center there, not a scaled-up phone screen.
- **Lists become tables on laptop**: contacts and property inventory switch from mobile's card-list to a real sortable table with more columns visible at once (budget, location, stage, owner, last activity) and denser row height — mouse + larger screen means more information density is appropriate, where mobile intentionally kept it sparse for thumb use.
- **The Journey Timeline signature element stays vertical even on desktop** — don't rotate it horizontal just because there's width available; a horizontal stepper loses the "package tracker" legibility that makes it work, and consistency between mobile and desktop matters for a small team that'll use both.
- **Agent and Cold Caller flows stay functionally mobile-first even on desktop** — same one-primary-action-per-screen, fast-logging forms — just laid out with more breathing room and a persistent sidebar instead of full-bleed mobile screens. Don't add extra fields or complexity just because desktop has space; the workflow speed rules still apply.

## Mobile-first interaction principles

- **Design for the smallest screen first**, then expand — not the reverse. Every core action (log a call, log a site visit, add a remark) must work perfectly at ~375px width before the laptop layout is considered.
- **Thumb-reachable primary actions**: the single most common action per screen (e.g. "Log Call") sits in the bottom third of the screen on mobile, not the top.
- **One primary action per screen.** Secondary actions go behind a menu, not next to the primary button — the busiest role on the busiest day (cold caller) will mis-tap otherwise.
- **Minimize typing.** Dropdowns, toggles, and tap-to-select wherever the input set is known (call outcome, property type, rent-vs-sale); free text only where it must be (notes/remarks).

## Role-specific home screens

- **Owner**: live activity feed + team performance snapshot + escalation inbox (three-panel on laptop, stacked on mobile)
- **Agent**: today's scheduled site visits + assigned leads queue
- **Cold Caller**: call queue with next lead front and center, one tap to start logging

## Interaction & accessibility rules

- **Status is always color + label, never color alone** — colorblind-safe, and the label is what actually gets read at a glance under sun glare on a phone screen.
- **Fast-logging forms (calls, remarks) use large tap targets** (minimum 44×44px); dropdowns default-open to the most common option, not alphabetical order (e.g. "Connected" and "Not Reachable" surface first).
- **Every list is filterable from a visible control**, not buried in a settings menu.
- **Empty states tell the user what to do next** ("No leads assigned yet — ask your manager to assign leads" beats a blank screen).
- **Offline/slow-connection states are explicit** — a visible "Saved, will sync" indicator when a log is queued offline (agents will be in basements/elevators/under-construction sites with poor signal).

## Trust & transparency in the UI

- **Staff-facing screens visibly show what's logged and to whom** — "You logged this call at 3:42pm" reinforces that logging is part of the job, not covert surveillance.
- **The owner's "who showed what to whom" view is the Journey Timeline**, filterable by agent/property/client — a trust and oversight tool that reads as a scannable timeline, not a raw data dump.

## Tone by screen density

- Keep the cold-calling and logging screens visually the **calmest** in the app — high call volume is inherently stressful; no extra visual noise on the highest-frequency screens.
- Reserve the Ink dark-card treatment and denser information layouts for the Owner's dashboard, where more density and visual weight are appropriate.

(When actual UI build begins, consult the `frontend-design` skill for the full execution pass — exact type pairing, spacing scale, and any additional signature touches — using this token system as the locked starting point rather than starting from a blank slate.)
