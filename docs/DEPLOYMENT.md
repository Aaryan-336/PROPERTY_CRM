# Deploying to Render + Vercel

Backend and database on Render, frontend on Vercel. About 20 minutes end to
end. The WhatsApp gateway is a separate decision — see the last section.

```
  Vercel                    Render
  ┌────────────┐            ┌──────────────┐     ┌─────────────┐
  │ Next.js    │──HTTPS────▶│ FastAPI      │────▶│ Postgres    │
  │ (web/)     │            │ balaji-api   │     │ balaji-db   │
  └────────────┘            └──────────────┘     └─────────────┘
                            ┌──────────────┐            ▲
                            │ extraction   │────────────┘
                            │ worker       │
                            └──────────────┘
```

---

## Before you start

The repo already carries what Render and Vercel need:

| File | Purpose |
|---|---|
| `render.yaml` | Blueprint: database + API + extraction worker |
| `backend/.python-version` | Pins Python 3.12.4 |
| `web/vercel.json` | Framework + region hint |

Three things were adjusted so a managed Postgres works at all — worth knowing
about because they change one security property:

1. **Migration `0001` skips its GRANT/REVOKE when the `balaji_app` role does
   not exist.** Render gives you one owner role, and granting to a
   non-existent role aborts the migration. See *Restoring the audit-log
   guarantee* below.
2. **`DATABASE_URL` is normalized** — Render issues `postgresql://…`, and
   SQLAlchemy needs `postgresql+psycopg://…` or it reaches for the uninstalled
   psycopg2.
3. **`MIGRATION_DATABASE_URL` is optional** and falls back to `DATABASE_URL`.

---

## Part 1 — Render (database + API)

### 1. Create the Blueprint

Render Dashboard → **New** → **Blueprint** → connect
`Aaryan-336/PROPERTY_CRM` → it picks up `render.yaml` → **Apply**.

This creates `balaji-db`, `balaji-api`, and `balaji-extraction-worker`.

> The worker is on the `starter` plan because Render does not offer background
> workers on free. If you are not using the WhatsApp feed yet, delete that
> service from `render.yaml` before applying and add it later.

### 2. Fill in the secrets Render can't generate

On **balaji-api** → *Environment*, the three marked `sync: false` are blank:

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | Leave blank for now — you need the Vercel URL first (step 5) |
| `ANTHROPIC_API_KEY` | Only if using the WhatsApp feed |

`JWT_SECRET` and `WHATSAPP_INGEST_SECRET` are generated for you. Copy
`WHATSAPP_INGEST_SECRET` if you plan to run the gateway.

### 3. Let it deploy

`preDeployCommand` runs `alembic upgrade head` against the attached database.
Watch the log for:

```
Running upgrade  -> 0001, Phase 1 schema.
[0001] role 'balaji_app' not present - skipping GRANT/REVOKE.
Running upgrade 0001 -> 0002, Phase 3 -- WhatsApp Property Feed Aggregator.
```

That notice is expected on Render. Then check health:

```bash
curl https://balaji-api.onrender.com/health
# {"status":"ok","phase":1,"push_enabled":false}
```

### 4. Create the first owner account

There is no public sign-up — by design, since this is an internal tool. Use
Render's **Shell** tab on `balaji-api`:

```bash
python -m app.seed --reset     # demo data + all five logins
```

**On anything real, do not run the seed.** Create one owner instead:

```bash
python - <<'EOF'
from app.db import SessionLocal, system_scope
from app.models import User
from app.security import hash_password
db = SessionLocal()
with system_scope():
    db.add(User(name="Balaji Rao", email="owner@yourfirm.com", role="owner",
                password_hash=hash_password("<a strong password>")))
    db.commit()
print("owner created")
EOF
```

Everyone else is added from the **Team** screen once you can sign in.

---

## Part 2 — Vercel (frontend)

### 5. Import the project

Vercel → **Add New** → **Project** → import `Aaryan-336/PROPERTY_CRM`.

**Set Root Directory to `web`.** This is the step people miss — the repo root
is not a Next.js app, and the build fails without it.

Framework preset should auto-detect as Next.js. Leave build/output as default.

### 6. Point it at the API

Project → *Settings* → *Environment Variables*:

| Name | Value | Environments |
|---|---|---|
| `API_URL` | `https://balaji-api.onrender.com` | Production, Preview, Development |

No `NEXT_PUBLIC_` prefix, deliberately: the browser never talks to FastAPI
directly. Every call goes through the Next server, which attaches the session
JWT from an httpOnly cookie. Exposing the API base to the client would not
break anything, but it would invite someone to call it directly and skip that.

Deploy. You get e.g. `https://property-crm.vercel.app`.

### 7. Close the CORS loop

Back on Render → **balaji-api** → *Environment*:

```
CORS_ORIGINS = https://property-crm.vercel.app
```

Comma-separate to add preview domains:

```
CORS_ORIGINS = https://property-crm.vercel.app,https://property-crm-git-main-you.vercel.app
```

Save — Render redeploys. **Until you do this, every request fails as a CORS
error** and the app looks broken with nothing useful in the UI.

### 8. Sign in

Open the Vercel URL and log in with the owner account from step 4.

---

## Part 3 — The WhatsApp gateway

The gateway is **not** in `render.yaml`, for two reasons:

1. It keeps a WhatsApp Web session in `.wa-session/`. Render's filesystem is
   ephemeral, so on the free plan every restart logs the account out and needs
   a fresh QR scan. It needs a **persistent disk** (paid) to survive restarts.
2. It drives a real WhatsApp account over an unofficial integration. Running it
   on hardware the firm controls — an office machine, a small VPS — keeps that
   blast radius where you can see it.

**Recommended:** run it on a machine in the office.

```bash
git clone https://github.com/Aaryan-336/PROPERTY_CRM.git
cd PROPERTY_CRM/gateway && npm install && cp .env.example .env
```

```bash
# gateway/.env
WHATSAPP_INGEST_SECRET=<the value Render generated on balaji-api>
API_BASE_URL=https://balaji-api.onrender.com
```

```bash
npm run pair      # QR-pair a dedicated number
npm run groups    # list group ids
npm start
```

Then add the groups in the CRM under **Owner → Inventory feed**.

**If you do want it on Render:** add a `worker` service with `rootDir: gateway`,
`startCommand: node src/index.js`, and a **disk mounted at
`/opt/render/project/src/gateway/.wa-session`**. Pairing needs the QR from the
logs — run `npm run pair` locally first and copy the session directory up, or
scan from the Render log output on first boot.

---

## Restoring the audit-log guarantee

Locally, `balaji_app` has `INSERT, SELECT` on `audit_log` and no `UPDATE` or
`DELETE`, so **Postgres itself** refuses to rewrite history. On a single-role
Render database that is skipped, and the guarantee drops to "the application
never issues the statement" — still true (`app/audit.py` only ever inserts),
but enforced one layer higher.

To get the database-level guarantee back, in Render's **PSQL** tab:

```sql
CREATE ROLE balaji_app LOGIN PASSWORD 'pick-something-long';
GRANT CONNECT ON DATABASE balaji_crm TO balaji_app;
GRANT USAGE ON SCHEMA public TO balaji_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO balaji_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO balaji_app;

-- the part that matters
REVOKE UPDATE, DELETE ON TABLE audit_log FROM balaji_app;
```

Then on `balaji-api` set:

- `DATABASE_URL` → the same host/database but as `balaji_app`
- `MIGRATION_DATABASE_URL` → the original owner URL (migrations need DDL)

Worth doing before the system holds real client data, since the audit trail is
the anti-leakage control the product exists for.

---

## Things that will bite you

| Symptom | Cause |
|---|---|
| Vercel build fails, "no Next.js detected" | Root Directory not set to `web` |
| Every API call fails, CORS error in console | `CORS_ORIGINS` missing the Vercel domain (step 7) |
| `ImportError: psycopg2` | An old `DATABASE_URL` bypassing normalization — it should start `postgresql://` or `postgresql+psycopg://` |
| Migration aborts, `role "balaji_app" does not exist` | Running a build from before this change — pull latest `main` |
| First request after idle takes ~50s | Render free tier spins down. Upgrade to `starter`, or accept it |
| Login works, then 401s everywhere | `JWT_SECRET` changed between deploys — it invalidates live sessions |
| Inventory feed shows "Extraction is not configured" | `ANTHROPIC_API_KEY` not set on **both** the API and the worker |
| Messages queue but never become listings | Extraction worker not running (free plan has no workers) |

## Costs

| Piece | Free? |
|---|---|
| Vercel (Hobby) | Yes |
| Render Postgres | Free 90 days, then ~$7/mo |
| Render web service | Free, sleeps after 15 min idle |
| Render worker | No — ~$7/mo, needed only for the WhatsApp feed |
| Anthropic API | Usage-based; only if using the feed |

A working CRM without the WhatsApp feed costs nothing beyond the database
after 90 days.
