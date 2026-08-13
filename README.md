# Balaji CRM

An internal CRM for a small real-estate brokerage: role-scoped lead management,
site-visit tracking, a cold-calling workflow, an immutable audit trail, and a
WhatsApp feed that turns broker-group chatter into one de-duplicated inventory.

Built around two problems the brokerage actually stated: the owner cannot see
what staff are doing, and the client list can walk out of the door with a
departing agent. Both are structural here, not features bolted on — role
scoping is enforced in the query layer and audit logging is middleware, so
neither can be forgotten by a future endpoint.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind, as an installable PWA |
| Backend | FastAPI + SQLAlchemy + Alembic |
| Database | PostgreSQL |
| Ingestion gateway | Node + Baileys (WhatsApp Web multi-device) |
| Extraction | Groq (`llama-3.3-70b-versatile`), JSON-schema structured outputs |

## Layout

```
backend/    FastAPI app, migrations, extraction worker, tests
web/        Next.js PWA
gateway/    WhatsApp ingestion gateway (separate service, own box)
docs/       PRD, architecture, data model, security model, roles matrix
```

## Running it

Requires PostgreSQL, Python 3.12+, and Node 20+.

```bash
# 1. Database roles + schema
createdb balaji_crm
psql balaji_crm -c "CREATE ROLE balaji_app LOGIN PASSWORD 'balaji_dev_pw';"
psql balaji_crm -c "CREATE ROLE balaji_migrator LOGIN PASSWORD 'balaji_dev_pw';"

# 2. Backend
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env          # fill in JWT_SECRET, and the Phase 3 keys if used
./.venv/bin/alembic upgrade head
./.venv/bin/python -m app.seed --reset
./.venv/bin/uvicorn app.main:app --port 8000

# 3. Frontend
cd ../web && npm install && npm run dev     # http://localhost:3000
```

Seeded logins are printed by `app.seed`; all use the password `balaji123`.

## WhatsApp inventory feed

Optional, and the most involved part. Full write-up in
[`docs/WHATSAPP_INGESTION.md`](docs/WHATSAPP_INGESTION.md) — including the
constraint that shapes it: **no official WhatsApp API can read group messages**,
so this drives a real account over WhatsApp Web. Use a dedicated number.

```bash
cd gateway && npm install && cp .env.example .env   # same secret as backend/.env
npm run pair      # QR-pair the account
npm run groups    # list group ids, then add them in the CRM (Owner → Inventory feed)
npm start

cd ../backend && ./.venv/bin/python -m app.workers.whatsapp   # extraction worker
```

Messages are stored raw before parsing, so a prompt fix can be replayed over
history. Reposts of the same flat merge into one listing rather than
duplicating it, and every sighting is kept so provenance stays auditable.

## Tests

```bash
cd backend && ./.venv/bin/pytest      # 118 tests
cd web && npx tsc --noEmit && npm run build
```

## Deploying

Render (API + Postgres) and Vercel (frontend): see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). A `render.yaml` blueprint is
included; set the Vercel project's Root Directory to `web`.

## Documentation

`docs/` holds the specs this was built against — `PRD.md`,
`ARCHITECTURE.md`, `DATA_MODEL.md`, `SECURITY_MODEL.md`,
`ROLES_PERMISSIONS.md`, `API_SPEC.md`, `DESIGN_RULES.md`, `PHASES.md`, and
`WHATSAPP_INGESTION.md`.
