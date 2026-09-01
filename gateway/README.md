# WhatsApp Ingestion Gateway

Reads the broker groups the owner has configured in the CRM and forwards every
message to the API's ingest webhook. Extraction and dedup happen on the backend
(`backend/app/workers/whatsapp.py`); this service does nothing but stay
connected and lose nothing.

## Read this before you set it up

**There is no official WhatsApp API that can read group messages.** The
official Cloud API only delivers messages sent *to* a registered business
number — group traffic is not available through it at any price tier. Reading
groups means driving a real WhatsApp account over the WhatsApp Web multi-device
protocol, which is what this gateway does (via
[Baileys](https://github.com/WhiskeySockets/Baileys), the library
`docs/TECH_STACK.md` already specifies).

What that means in practice:

- **Use a dedicated phone number**, never a personal or business-critical one.
  WhatsApp's terms permit banning accounts that automate, and while a
  read-only, non-broadcasting client like this one is low risk, the risk is not
  zero.
- **The account must actually be a member of every group you want to read.**
  There is no way to read a group from outside it.
- **The session can drop** (phone offline for a long stretch, device unlinked,
  WhatsApp update) and need re-pairing by QR. The CRM's inventory feed screen
  shows when messages stopped arriving.
- The gateway **only reads**. It never posts, replies, or marks itself online.

## Setup

Needs **Node 22.9+** — the npm scripts load `.env` with Node's own
`--env-file-if-exists` rather than pulling in a dependency for it. The
`-if-exists` form matters in a deployment, where the config arrives as real
environment variables and there is no file to read.

```bash
cd gateway
npm install
cp .env.example .env
# Put the same secret here as in backend/.env → WHATSAPP_INGEST_SECRET
```

### 1. Pair the account

```bash
npm run pair
```

Scan the QR from the dedicated phone: **WhatsApp → Settings → Linked devices →
Link a device**. The session is saved to `.wa-session/` and survives restarts.

### 2. Find the group ids

```bash
npm run groups              # all of them
npm run groups -- property  # only those whose name matches
```

Prints every group the account is in, with its id (`…@g.us`) and name. A working
account is easily in several hundred groups and only a handful carry inventory,
so pass a search word to narrow it.

Groups whose metadata has not synced yet show as *(name not synced yet)* and
sort to the bottom. Their ids still work; re-run once the session has been
connected for a while and most will have filled in.

### 3. Add the groups in the CRM

Sign in as the owner → **Inventory feed** → *Add group*, and paste the id and a
name. Only groups added there are ever read; the gateway re-reads that list
every 60 seconds, so switching a group off in the UI takes effect without a
restart.

### 4. Run it

```bash
npm start
```

Then run the extraction worker on the backend, which turns the stored messages
into inventory:

```bash
cd ../backend
./.venv/bin/python -m app.workers.whatsapp
```

## How it avoids losing or duplicating messages

The two failure modes that matter are *dropping* a listing and *double-listing*
one. They are handled at different layers:

- **Dropping** — every message is appended to `.wa-outbox.jsonl` the moment it
  arrives, before any network call. It is removed only once the API has
  acknowledged it. A crash, an API restart, or an overnight outage costs a
  replay, never data.
- **Doubling** — the API keys on WhatsApp's own `wa_message_id` and ignores
  anything it has already stored, so replaying is free. Beyond that, the
  extraction pipeline deduplicates at the *listing* level, so the same flat
  posted by six brokers is still one row in inventory.

Requests are signed with `HMAC-SHA256(secret, "<unix-ts>.<raw body>")` and the
API rejects anything unsigned, tampered with, or older than five minutes. The
gateway never holds a user credential — it cannot read leads, contacts, or
anything else in the CRM, which is the point of it living on its own box.

## Operating notes

- **`--list-groups` and `--pair` exit after running**; only `npm start` stays up.
- **Media without a caption is skipped** — the pipeline extracts from text. A
  photo of a flat with the details typed underneath works fine; a bare photo
  has nothing to read.
- **Reconnecting resumes where the CRM stopped.** On connect the gateway reads
  a watermark per group from `/internal/whatsapp/groups` -- the newest message
  the CRM has actually stored -- and forwards everything posted since. A laptop
  that slept through the weekend catches up on it instead of losing it. The
  watermark lives in the database rather than on this box, because this box is
  the half that sleeps.
- **`BACKFILL_MAX_AGE_MS` (default 7 days) caps how far a resume reaches.** A
  group quiet for longer than this resumes from the cap, so switching a dormant
  group back on cannot replay a quarter of dead listings.
- **`MAX_MESSAGE_AGE_MS` (default 24h) applies only where there is no
  watermark** -- a fresh pairing, or a group just added. That is history rather
  than a gap, so it stays out. Raise it for a one-off backfill of a new group.
- **History is filtered, not requested.** `syncFullHistory` stays off: the
  gateway never asks WhatsApp for more than an ordinary desktop client gets on
  linking. It now keeps the slice of that it is sent, for watched groups only,
  instead of discarding all of it.
- **The session outlives the process, by weeks.** Losing the connection is
  almost never losing the login. `.wa-session/creds.json` holds a linked
  device; WhatsApp keeps it linked until somebody unlinks it from the phone.
  If messages stop, check whether the process is running *before* re-pairing --
  re-pairing an account repeatedly is what gets a number flagged, and it is the
  one recovery step that cannot be undone.
- **The gateway no longer exits on a dropped connection.** Baileys throws
  `Connection Closed` from inside its own async queues when a socket goes away
  with work in flight, and Node terminates the process on an unhandled
  rejection. That made every wifi blip a coin toss. `src/resilience.js`
  classifies those, and a logout (401) is deliberately *not* in that class --
  it needs a person, and swallowing it would leave the gateway spinning
  forever. Anything unrecognised is logged loudly and reported to the CRM.
- **A stall watchdog reconnects after 2 minutes down** if the close handler's
  own retry never fired.
- **Never commit `.wa-session/`.** It is the login.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `logged out — the linked device was removed` | Someone unlinked the device from the phone. Delete `.wa-session/` and re-pair. |
| Ingestion stops with no error in the CRM | Check the process is alive first (`pgrep -f src/index.js`). Historically it exited on a Baileys unhandled rejection after a wifi drop; the log ends in a stack trace and a bare `Node.js v22.x` line. Guarded now — if you see that footer again, the error above it is a new class worth reporting. |
| `API ignored N unwatched group(s)` | Normal right after removing a group; already-journalled messages are discarded by the API. |
| `delivery failed … retrying` | API down or the secret does not match `backend/.env`. Messages stay on disk. |
| Messages arrive but no inventory appears | The extraction worker is not running, or `GROQ_API_KEY` is unset. Check **Inventory feed** in the CRM — it reports both. |
| Reconnected but the gap was not filled | The group had no watermark (nothing ever stored), so the 24h window applied — or the gap was wider than `BACKFILL_MAX_AGE_MS`. `GET /healthz` reports `backfilled`. |
