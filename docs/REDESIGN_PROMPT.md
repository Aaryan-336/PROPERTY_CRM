# Master Prompt — Balaji CRM Redesign

Hand this to a designer, a design agency, or an AI coding agent. It is written
to be pasted whole. Everything in it is true of the shipped product as of
September 2026; where it states a constraint, that constraint is enforced in
the API and cannot be designed around.

Read §6 before proposing anything. It is the part most likely to be violated by
a redesign that looks excellent.

---

## The prompt

> You are redesigning **Balaji CRM**, an internal tool used by one small
> real-estate brokerage in Mumbai. It is not a SaaS product, it has no
> marketing site, and it will never have public users. Roughly a dozen people
> use it, most of them on a phone, most of them outdoors.
>
> Your job is to raise the visual and interaction quality of the product
> without breaking the three things it exists to do, and without making it
> slower to operate. Read the whole brief before proposing a direction.

---

## 1. What the product is

A brokerage owner runs a team of closing agents and cold callers. Before this
tool, the business ran on WhatsApp, phone calls and scattered notes. Three
concrete problems followed, and the product is an answer to all three:

| Problem | What the product does about it |
|---|---|
| Property listings are scattered across hundreds of WhatsApp groups | Reads selected groups automatically and turns free-text posts into one searchable, deduplicated inventory |
| The owner cannot see which agent is showing which flat to which client | Records every call, showing and stage change, attributed and timestamped |
| Staff can walk out with the firm's client list | Role-scoped access plus an audit trail on every privileged action |

The third one is not a feature, it is a threat model. The adversary is a person
who already has a legitimate login.

## 2. Who uses it

Three live roles. A fourth, Manager, is modelled in the database but not yet
activated — design for three, leave room for a fourth that behaves like a
team-scoped Owner.

- **Owner** — the firm's head. Sees everything: every lead, every agent, every
  property, the audit log, the WhatsApp configuration. The only role that can
  delete, export, import, reassign, or read the raw message feed.
- **Agent** — closing and field staff. Their own assigned leads, the firm's
  shared inventory, their showings. Cannot export, cannot reassign a lead to
  themselves, cannot delete a listing.
- **Cold Caller** — the calling team. A queue of their assigned leads, showing
  name and number only. No lead book, no inventory, by design.

**The single most important structural fact:** these are not one interface with
permissions applied. They are three different applications behind one login,
with different navigation and different data. A cold caller does not see a
greyed-out Inventory tab; the inventory endpoint refuses their role outright.

## 3. Every screen you are designing

Flat hierarchy — there is no nested menu anywhere in the product.

| Route | Screen | Reached by |
|---|---|---|
| `/` | Home — a different dashboard per role | All |
| `/queue` | Call queue — the next lead to ring | Cold Caller |
| `/queue/session` | Call console — one lead, full screen | Cold Caller |
| `/my-calls` | My calls — what I logged today | Cold Caller |
| `/contacts` | Leads — the lead book, filterable | Owner, Agent |
| `/contacts/[id]` | Lead detail — journey, calls, interests | Owner, Agent |
| `/contacts/new` | Add lead | Owner, Agent |
| `/properties` | Inventory — cards on phone, table on laptop | Owner, Agent |
| `/properties/[id]` | Listing detail — provenance, showings | Owner, Agent |
| `/properties/new` | Add listing — manual entry | Owner, Agent |
| `/showings` | Showings — site visits scheduled and done | Owner, Agent |
| `/escalations` | Escalations — leads flagged for the owner | Owner |
| `/feed` | Activity — firm-wide, live | Owner |
| `/inventory-feed` | Inventory feed — the WhatsApp pipeline console | Owner |
| `/import` | Import leads — spreadsheet upload | Owner |
| `/team` | Team — staff and access | Owner |
| `/team/performance` | Performance — calls, showings, escalations | Owner |
| `/audit` | Audit — who did what, when | Owner |
| `/account` | Your account — password | All |

Mobile navigation is a floating pill holding at most five icon targets.
Everything a role may open stays reachable; the pill only decides what is one
tap away versus one tap behind **More**:

- **Owner** — Home, Leads, Inventory, Escalations
- **Agent** — Home, Leads, Inventory, Showings
- **Cold Caller** — Home, Queue, My calls

On a laptop the pill becomes a fixed left rail: same items, same order, same
dark surface, turned ninety degrees.

## 4. The vocabularies the interface must express

These are fixed. Renaming them in the UI is fine; adding to or collapsing them
is a product change, not a design change.

- **Lead stages** — `new` → `contacted` → `site_visit_scheduled` → `visited` →
  `negotiating` → `closed` | `lost`
- **Call outcomes** — `connected`, `not_reachable`, `not_interested`,
  `interested`, `callback_requested`, `wrong_number`
- **Temperature** — `hot`, `warm`, `cold`
- **Property interest** — `inquired` → `site_visit_scheduled` →
  `site_visit_done` → `negotiating`
- **Listing** — `rent` | `outright`; `apartment`, `villa`, `plot`,
  `commercial`; `available` | `blocked` | `sold`
- **Extraction review** — `auto_accepted`, `needs_review`, `confirmed`,
  `rejected`
- **Message ingestion** — `pending` → `processing` → `extracted` | `duplicate`
  | `not_listing` | `failed`

## 5. The design system already in place

You may replace this. You may not replace it by accident — if you change a
token, say so and say why.

**Colour**

| Token | Hex | Role |
|---|---|---|
| Ink | `#15141B` | Dark surfaces, reserved for what the owner most needs to trust |
| Parchment | `#F6F2EA` | App background, warm rather than sterile white |
| Card White | `#FFFFFF` | Routine cards on Parchment |
| Sandstone | `#C9863E` | Primary accent — CTAs, active states |
| Deep Teal | `#1E5C56` | Verified, owner-visible, trust states |
| Signal | `#D9482F` | Hot leads and escalations only, used sparingly |
| Slate | `#55505F` | Secondary text |
| Hairline | `#E2DBCD` | Borders |

There is deliberately **no dark mode**. The whole hierarchy depends on Ink
surfaces reading differently from routine ones; a dark theme collapses that
distinction. If you want one, you must first propose a replacement for the
"this matters" signal.

**Type** — a geometric grotesk for display (currently Space Grotesk), a warm
humanist sans for body (Plus Jakarta Sans), and a mono/tabular face for prices,
phone numbers, IDs and timestamps (JetBrains Mono) so figures align in lists.

**Form** — 20–28px corner radii. Rounded and tactile, not sharp corporate
rectangles, and not full bubble either.

**Signature element** — a vertical checkpoint timeline: connected circular
nodes, each with a status icon and a timestamp. Used for a lead's pipeline, a
property's showing history, and a call's escalation chain. It stays vertical on
desktop. This is the one element the product should be remembered by, and it is
not decoration: "where is this thing now, and who touched it" is the product's
actual differentiator.

**Motion** — the interaction layer is roughly 2KB of CSS and no JavaScript
dependency:

- Every control answers the thumb: `scale(0.97)` on press, **80ms down, 220ms
  back**. Fast in, slow out — equal timings are what make web apps feel rubbery.
- Large surfaces press to `0.985`, because scale reads as a proportion of the
  element.
- Text inputs are excluded — a field is entered, not pressed.
- Only `transform` and `opacity` animate, so everything stays on the compositor.
- Navigation is acknowledged the instant it is tapped, not when the page
  arrives.
- `prefers-reduced-motion` swaps movement for a brightness shift rather than
  removing the feedback.

If your redesign needs a motion library, treat that as a signal it has gone too
far.

## 6. Hard constraints — read before proposing anything

**These are enforced in the API. A design that assumes otherwise cannot be
built.**

1. **A Cold Caller must never see the lead book or the inventory.** Not
   filtered, not partial, not "just the matching flat". The endpoints refuse
   the role. Any concept that shows a caller more than one client at a time is
   out.
2. **Ownership is never self-service.** No design may offer an Agent a way to
   reassign a lead to themselves.
3. **Export, delete, import and audit are Owner-only.** Do not design a bulk
   action into a shared surface.
4. **Status is never colour alone.** Always colour *and* a text label —
   colourblind-safe, and the label is what actually gets read in sun glare.
5. **One primary action per screen.** Secondary actions go behind a menu, never
   beside the primary one; the busiest role on the busiest day will mis-tap.
6. **Primary actions sit in the bottom third on mobile**, where a thumb already
   is.
7. **Minimise typing.** Chips and toggles wherever the option set is known;
   free text only for remarks and notes.
8. **Every core action must work at 375px wide, one-handed, in under fifteen
   seconds.** This is the test every screen is judged against.
9. **The app is an installed PWA on iOS.** It renders under the status bar, so
   every top edge needs the safe-area inset, and the bottom dock needs the home
   indicator inset.
10. **The API is on a free tier that sleeps.** Some screens will wait seconds
    for data. Loading is a design state, not an afterthought.

## 7. What is actually wrong today

Be specific about what you are fixing. The known weaknesses, in order:

1. **The product reads as competent but joyless.** Correct hierarchy, correct
   spacing, very little personality. It is a design system applied, not a
   product designed.
2. **The three role-homes are underdeveloped.** `/` does the least work of any
   screen, and it is the screen every user opens first.
3. **Empty and loading states are thin.** A new firm's first week is mostly
   empty screens, and they currently say very little.
4. **The inventory feed console is dense and technical.** It exposes real
   operational truth — queue depth, stalled claims, extraction failures — in
   language closer to the database than to the owner.
5. **Density is uniform.** A cold caller between two calls and an owner
   reviewing at 9pm are given the same information rhythm.
6. **The desktop layout is competent but conservative.** The Owner dashboard in
   particular should read as a command centre and currently does not.

## 8. What to deliver

1. A stated direction — palette, type pairing, and layout concept — in a
   paragraph, before any screens.
2. The three role-homes (`/`) first. They are the highest-leverage screens and
   the weakest today.
3. Then, in order: the call console, the lead detail, the inventory list and
   listing detail, the escalation inbox.
4. Mobile at 375px first, every time. Desktop after, and not as the mobile
   layout stretched wide.
5. Every state for every screen: loaded, loading, empty, error, and — where the
   role changes what is shown — once per role.
6. A note on anything you changed in §5, and why.

## 9. Do not

- Do not propose a generic SaaS dashboard. The reference points for this
  product are consumer apps with confident dark surfaces and tactile cards, not
  admin panels.
- Do not add a navigation level. The flat hierarchy is load-bearing for
  one-handed use.
- Do not use colour as the only carrier of meaning anywhere.
- Do not introduce a component library whose look overrides the identity above.
- Do not design screens that assume fast data.
- Do not solve the "it feels dead" problem with more animation. It was a
  feedback problem, and it is largely fixed; the remaining gap is
  compositional, not kinetic.

---

## How to use this prompt

**With an AI coding agent** — paste §1–§9 verbatim, then add the single screen
you want built and the phrase *"mobile at 375px first; show me the empty and
loading states too."* The constraints in §6 are the part that stops a plausible
design from being unbuildable.

**With a human designer** — send this plus the product reference document. Ask
for §8.1 (the stated direction) before any screens, so the direction is agreed
before the work is spent.

**Reviewing what comes back** — check it against §6 first, not against taste.
A design that violates a hard constraint is not a design that needs revision;
it is a design for a different product.
