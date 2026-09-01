# WhatsApp Property Feed Aggregator

How hundreds of broker-group messages become one searchable, de-duplicated
inventory. This is `FEATURE_LIST.md` module 2 [P3] and the data flow sketched in
`ARCHITECTURE.md`, as built.

## First, the constraint that shapes everything

**There is no official WhatsApp API that can read group messages.** The Cloud
API only delivers messages sent *to* a registered business number; group traffic
is not exposed on any tier. Reading groups means driving a real WhatsApp account
over the WhatsApp Web multi-device protocol — which is what `TECH_STACK.md`
already chose (Baileys) and what `gateway/` implements.

Practical consequences, worth stating plainly to whoever operates this:

- It is an **unofficial integration**. WhatsApp's terms permit banning accounts
  that automate. Use a dedicated number, never a personal or business-critical
  one.
- The account **must be a member** of every group it reads.
- The session **can drop** and need re-pairing by QR. The Inventory feed screen
  shows when messages stopped arriving.

The architecture assumes all three will happen and is built so none of them
loses data.

## The pipeline

```
WhatsApp group
     │  (Baileys, read-only)
     ▼
gateway/                      ← separate service, own box, no CRM credentials
     │  journal to disk FIRST, then POST
     │  HMAC-SHA256(secret, "<ts>.<body>")
     ▼
POST /internal/whatsapp/ingest    ← stores raw, verbatim. No parsing.
     │                              idempotent on wa_message_id
     ▼
whatsapp_messages (status=pending)
     │
     ▼
app/workers/whatsapp.py       ← claims a batch with SKIP LOCKED
     │
     ├─► app/extraction.py        Groq chat completions, JSON-schema output.
     │                            "Is this inventory?" + fields, verbatim.
     ├─► app/listing_normalize.py "1.2 Cr" → 12000000. Deterministic, tested.
     └─► app/property_dedup.py    Blocking key → weighted fuzzy score.
              │
              ├── new      → INSERT properties + property_sources(origin)
              └── repost   → property_sources(duplicate) + fill gaps only
     ▼
Unified inventory, searchable by every role
```

## Why each seam is where it is

**The gateway is a separate service.** It has a different failure mode from the
API (session drops, pairing expiry, rate limits) and it is the one component
built on an unofficial integration. Isolating it bounds the blast radius of
both. It holds no user credential and cannot read leads or contacts — only the
signing secret, which authorises exactly one thing: submitting messages.

**Messages are stored raw, before any parsing.** The gateway's job is to lose
nothing; the extractor's job is to interpret. Keeping them separate means a
prompt or parser improvement can be *replayed over history*
(`POST /whatsapp/reprocess/{id}`) instead of the data being lost to a bad early
extraction.

**The model reads; Python converts.** The extractor is asked for values
*verbatim* — `"1.2 Cr"`, not a number — because models are reliable at copying
what they read and unreliable at arithmetic. Every unit conversion happens in
`listing_normalize.py`, which is pure and unit-tested. A price misparse silently
lists a ₹85,000 flat at ₹8.5 crore, and nothing downstream can detect that, so
it is the one thing that must not be probabilistic.

**Dedup splits when uncertain.** A false merge hides a real flat from every
agent and is invisible until a deal is lost. A false split shows one flat twice
— visible, annoying, fixable by hand. The threshold is set accordingly, and BHK,
listing type, and large price/area gaps are *hard rejects* rather than scoring
penalties.

**Merging is additive only.** A repost fills fields the original lacked; it
never overwrites a value the firm already holds. Otherwise the newest, sloppiest
post silently rewrites a listing an agent has already quoted — or a manual
listing someone curated by hand.

## Handling the messy reality of group messages

The extractor must handle all of these from the same group on the same day:

| Message | Verdict |
|---|---|
| `3bhk lodha amara thane w 1.35cr carpet 780 semi furnished 98765...` | 1 listing |
| A formatted block with `Building:` / `Config:` / `Rent:` labels | 1 listing |
| `*FRESH INVENTORY* 1) 1bhk … 2) 2bhk … 3) Shop …` | 3 listings |
| `anyone has 4bhk in powai budget 4-5cr? client waiting` | **not** inventory — this is demand |
| `Good morning all 🙏` | not inventory |
| `is the andheri flat still available?` | not inventory |

The requirement post is the one that matters most. Ingesting "wanted" messages
would fill the searchable inventory with flats that **do not exist**, which is
worse than missing a listing — so the prompt is explicit about it, and the
default when uncertain is to reject.

Price shorthand is handled deterministically, including the unitless cases
brokers actually write:

| Written | Rent means | Sale means |
|---|---|---|
| `1.2` | ₹1.2 lakh/month | ₹1.2 crore |
| `85` | ₹85,000/month | ₹85 lakh |
| `85000` | ₹85,000 (already absolute) | — |

The rule: a *fraction* is lakh/crore shorthand, a *whole number* is
thousand/lakh, and a value already plausible for its listing type is left alone.
Magnitudes that could only be a mislabel (a "rent" of ₹1.2 crore) are rescaled;
the listing *type* is never rewritten.

## Operating it

```bash
# 1. Backend: secret + model credentials
#    backend/.env → WHATSAPP_INGEST_SECRET, GROQ_API_KEY
cd backend && ./.venv/bin/alembic upgrade head

# 2. Gateway (separate box in production) — must stay running
cd gateway && npm install && cp .env.example .env   # same secret
npm start

# 3. Everything else is in the CRM: Owner → Inventory feed
#    - "Connect WhatsApp" → a QR appears on screen → scan it with the phone
#    - the groups the account is in then list themselves; tap the ones to read
#
#    npm run pair / npm run groups still exist and do the same job from a
#    terminal. They are for diagnosing a broken deployment, not for the owner.

# 4. Extraction worker
cd backend && ./.venv/bin/python -m app.workers.whatsapp

#    Useful while tuning the prompt — extracts and prints, writes nothing:
./.venv/bin/python -m app.workers.whatsapp --dry-run
```

### Coming back after a disconnect

The gateway is the disposable half of this pair. It runs on a laptop that
sleeps, or a host whose filesystem is restored from the repo on every deploy.
So it must be able to go away and come back without the firm losing the
messages posted in between — and it cannot be the thing that remembers where it
got to.

The database remembers instead. `WhatsAppGroup.last_message_at` is already the
newest message stored for a group, so `/internal/whatsapp/groups` hands it back
with the watch list, and the gateway resumes from there:

| Situation | Resume point | Why |
|---|---|---|
| Group has a watermark | The watermark | Everything after it was posted while the gateway was away. That is the gap, and it is exactly what the owner expects to find waiting. |
| Group has none | `MAX_MESSAGE_AGE_MS` (24h) | A fresh pairing, or a group just switched on. There is no gap, only history — and history is somebody else's dead inventory. |
| Watermark older than `BACKFILL_MAX_AGE_MS` (7d) | The cap | A group quiet since spring is an archive, not a gap. Without the cap, switching it back on replays a quarter and bills a full re-extraction. |

Two things make this safe to run at all:

**Duplicates are free.** Ingest is idempotent on `wa_message_id`, so an overlap
between what the gateway replays and what the CRM already holds costs one
rejected row. That is what lets the resume point be approximate — it can err
towards sending too much, because only the direction that sends too little
loses anything.

**It filters history rather than asking for more.** `syncFullHistory` stays
off. The gateway still never requests more scrollback than an ordinary desktop
client gets on linking — pulling months across hundreds of groups is the single
most abnormal-looking thing a new device can do, and this account belongs to a
working brokerage. What changed is that the slice WhatsApp sends unprompted is
now kept for watched groups instead of discarded wholesale. The watch list is
applied before decoding, so a group the owner never picked is not read even in
passing.

`GET /healthz` on the gateway reports `backfilled` — how much of this process's
traffic was recovered rather than heard live. A reconnect that closed a real
gap says so in a number, rather than leaving it to be inferred from whether the
inventory looks right.

### Pairing from the browser

The owner holds the phone; the gateway holds the terminal. So the QR travels
between them through the API:

```
owner taps Connect
  → POST /whatsapp/pair            records pair_requested_at
  → gateway polls /internal/whatsapp/commands   (every ~4s, HMAC-signed)
  → claims the command, which clears it        (claim-on-read)
  → clears .wa-session, opens a fresh socket
  → WhatsApp emits a QR, rotating every ~20s
  → POST /internal/whatsapp/session            with the payload + a 20s TTL
  → the owner's screen polls /whatsapp/session and renders it client-side
```

On connect the gateway also uploads every group the account is in
(`POST /internal/whatsapp/directory`), which is what the picker lists. That
table is a **cache, not a decision**: a row there means the group exists, and
nothing is read until the owner taps it and creates a `whatsapp_groups` row —
the only table the ingest webhook checks.

Two deliberate choices, both about not getting the number banned:

- **Claim-on-read.** A command left set until the gateway confirmed success
  would mean a gateway restarting mid-pairing wipes its session again on every
  boot — a re-pair loop against WhatsApp's servers. Losing a command costs one
  more press.
- **A cooldown in the gateway** (`REPAIR_COOLDOWN_MS`, 60s). Connect is one tap
  on a phone; a double tap must not become two relinks.

**The gateway has to be running for any of this to work.** It is the only
process that can produce a QR, and it holds the socket — so it needs somewhere
always-on: a paid Render worker, a small VPS, or a machine at the office that
stays on. A free-tier web service that sleeps after 15 idle minutes will drop
the WhatsApp session every time it does. Set `PORT` when the host requires a
listening process; the gateway then answers `/health` with its connection state
and nothing else.

**Two silent failure modes**, both surfaced explicitly on the Inventory feed
screen rather than left to be inferred from an inventory list that stopped
growing:

- *Extraction not configured* — no `GROQ_API_KEY`. Messages accumulate as
  `pending`; nothing becomes inventory.
- *No messages in 24h* — groups are quiet, or the gateway lost its session.

## Cost

Batched (8 messages per request) with the system prompt cached, at `effort:
low`. Batching amortises the cached prefix across many messages; the alternative
— one uncached call per message — is the difference between a rounding error and
a real bill at brokerage volumes. Non-listings are rejected by the model in the
same call that would have extracted them, so chatter costs input tokens only.

## Security posture

- The webhook **fails closed**: no secret configured → `503`, not open.
- Signature covers the **raw body bytes** and a timestamp; tampering and replay
  both fail. (The signature is computed over raw bytes rather than a
  re-serialized object precisely so Python's and Node's JSON spacing differences
  cannot break verification.)
- `whatsapp_groups` and `whatsapp_messages` are **guarded tables** in
  `app/db.py`: a future endpoint that forgets to scope them returns nothing
  rather than the raw feed.
- Group configuration and the raw feed are **Owner-only**
  (`ROLES_PERMISSIONS.md`). Which groups the firm sources from is competitive
  information, and message bodies carry counterparty numbers the firm never
  chose to publish.
- Broker phone numbers land on `properties`, **never** in `contacts` — they are
  counterparties, not the firm's leads, and must never appear in the client list
  or an export of it.
