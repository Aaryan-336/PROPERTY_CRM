# Data Model — Real Estate Broker CRM

Builds on the generic schema and real-estate domain variant from the `crm-leadgen-builder` skill (`references/schema.md`, `references/real_estate_domain.md`), extended with roles, audit logging, and call logs specific to this build.

```sql
-- ============ USERS & ROLES ============

CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT UNIQUE,
    phone           TEXT,
    role            TEXT NOT NULL,   -- 'owner', 'manager', 'agent', 'cold_caller'
    manager_id      BIGINT REFERENCES users(id),  -- for team scoping (phase 2)
    is_available    BOOLEAN DEFAULT TRUE,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

-- ============ CONTACTS / LEADS ============

CREATE TABLE contacts (
    id                      BIGSERIAL PRIMARY KEY,
    first_name              TEXT NOT NULL,
    last_name               TEXT,
    email                   TEXT,
    phone                   TEXT,
    phone_masked            BOOLEAN DEFAULT FALSE,   -- if true, only Owner/Manager see full phone
    lead_source             TEXT,        -- 'instagram', 'whatsapp_group', 'walk_in', 'referral', 'portal'
    campaign                TEXT,
    budget_min              NUMERIC(14,2),
    budget_max              NUMERIC(14,2),
    preferred_locations     TEXT[],
    property_type_interest  TEXT,
    buyer_type              TEXT,        -- 'end_user', 'investor'
    lead_score              INTEGER DEFAULT 0,
    stage                   TEXT DEFAULT 'new',  -- pipeline stage
    owner_id                BIGINT REFERENCES users(id),   -- assigned agent
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at              TIMESTAMPTZ
);
CREATE INDEX idx_contacts_owner ON contacts(owner_id);
CREATE INDEX idx_contacts_phone ON contacts(phone) WHERE deleted_at IS NULL;

-- ============ PROPERTIES ============

CREATE TABLE properties (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT,
    location        TEXT NOT NULL,
    building        TEXT,
    property_type   TEXT,          -- 'apartment', 'villa', 'plot', 'commercial'
    listing_type    TEXT NOT NULL, -- 'rent', 'outright'
    price           NUMERIC(14,2),
    status          TEXT DEFAULT 'available',  -- 'available', 'blocked', 'sold'
    source          TEXT DEFAULT 'manual',      -- 'manual', 'whatsapp_group'
    raw_message     TEXT,          -- original WhatsApp text, if source = whatsapp_group
    source_group    TEXT,
    posted_by_agent_id BIGINT REFERENCES users(id),  -- if it's the firm's own listing
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_properties_location ON properties(location);
CREATE INDEX idx_properties_listing_type ON properties(listing_type);
CREATE INDEX idx_properties_price ON properties(price);

CREATE TABLE property_interests (
    contact_id      BIGINT REFERENCES contacts(id),
    property_id     BIGINT REFERENCES properties(id),
    shown_by_agent_id BIGINT REFERENCES users(id),   -- WHO showed it — core to owner visibility
    interest_level  TEXT,        -- 'inquired', 'site_visit_scheduled', 'site_visit_done', 'negotiating'
    shown_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (contact_id, property_id, shown_at)
);

-- ============ CALL LOGS (cold calling + general) ============

CREATE TABLE call_logs (
    id              BIGSERIAL PRIMARY KEY,
    contact_id      BIGINT REFERENCES contacts(id),
    caller_id       BIGINT NOT NULL REFERENCES users(id),
    outcome         TEXT NOT NULL,   -- 'connected', 'not_reachable', 'not_interested', 'interested', 'callback_requested', 'wrong_number'
    temperature     TEXT,            -- 'hot', 'warm', 'cold'
    notes           TEXT,
    flagged_for_owner BOOLEAN DEFAULT FALSE,
    follow_up_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_call_logs_contact ON call_logs(contact_id, created_at DESC);
CREATE INDEX idx_call_logs_flagged ON call_logs(flagged_for_owner) WHERE flagged_for_owner = TRUE;

-- ============ ACTIVITIES (general — site visits, notes, status changes) ============

CREATE TABLE activities (
    id              BIGSERIAL PRIMARY KEY,
    contact_id      BIGINT REFERENCES contacts(id),
    property_id     BIGINT REFERENCES properties(id),
    user_id         BIGINT REFERENCES users(id),
    type            TEXT NOT NULL,   -- 'site_visit', 'note', 'stage_change', 'follow_up'
    body            TEXT,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_activities_contact ON activities(contact_id, occurred_at DESC);

-- ============ AUDIT LOG (append-only, never deleted) ============

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    action          TEXT NOT NULL,     -- 'view', 'edit', 'export', 'delete', 'reassign'
    resource_type   TEXT NOT NULL,     -- 'contact', 'property', 'call_log'
    resource_id     BIGINT,
    detail          JSONB,             -- e.g. {"exported_count": 240} for exports
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_log_user ON audit_log(user_id, occurred_at DESC);
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);
```

## Notes

- `property_interests` uses `(contact_id, property_id, shown_at)` as a composite key rather than a simple unique pair, because the same agent may legitimately show the same property to the same client more than once (follow-up visit) — each showing is its own event, which is exactly what the owner's "who showed what to whom" view needs.
- `audit_log` is intentionally denormalized (JSONB `detail`) and has no `deleted_at` — it must never be edited or removed by application code, including by Owner-role UI actions. If a database-level protection is available (e.g. a revoked UPDATE/DELETE grant for the app's DB role on this table), apply it.
- `contacts.phone_masked` is a flag the API layer checks — the actual masking logic (return last 4 digits vs. full number) lives in the API response serialization, not the DB.
