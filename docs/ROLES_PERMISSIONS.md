# Roles & Permissions Matrix — Real Estate Broker CRM

## Roles

- **Owner** — firm head, full visibility and control
- **Manager** — oversees a sub-team (Phase 2), scoped version of Owner's oversight powers
- **Agent** — closing/field agent, works assigned leads
- **Cold Caller** — calling team, works a call queue

## Permission matrix

| Capability | Owner | Manager | Agent | Cold Caller |
|---|:---:|:---:|:---:|:---:|
| View all contacts (firm-wide) | ✅ | Team only | ❌ (own only) | ❌ |
| Browse the lead list / open a lead | ✅ | ✅ | ✅ (own only) | ❌ — queue only, name + number |
| Create/edit contacts | ✅ | ✅ | ✅ (own only) | ✅ (limited fields — remarks) |
| Delete contacts (soft delete) | ✅ | ✅ | ❌ | ❌ |
| Bulk export contacts | ✅ | ✅ (own team) | ❌ | ❌ |
| View full phone/email (unmasked) | ✅ | ✅ | Only after first logged interaction | Number of the lead being called |
| Reassign lead ownership | ✅ | ✅ (own team) | ❌ (request only) | ❌ |
| View all properties/inventory | ✅ | ✅ | ✅ | ❌ |
| Add/edit property listings | ✅ | ✅ | ✅ | ❌ |
| Delete a property listing | ✅ | ❌ | ❌ | ❌ |
| View firm-wide activity feed | ✅ | Team only | ❌ (own activity only) | ❌ (own activity only) |
| View "who showed what to whom" | ✅ | Team only | Own records only | ❌ |
| View team performance dashboard | ✅ | Team only | ❌ | ❌ |
| Log a call | ✅ | ✅ | ✅ | ✅ |
| Flag/escalate to owner | ✅ (receives) | ✅ (receives, team) | ✅ (can flag) | ✅ (can flag) |
| View audit log | ✅ (full) | ✅ (team) | ❌ | ❌ |
| Manage users/roles | ✅ | ❌ | ❌ | ❌ |
| Configure WhatsApp ingestion groups | ✅ | ❌ | ❌ | ❌ |

## Cold Caller scope (revised)

A Cold Caller sees **one surface: their queue**, and of the client only a
**name and a mobile number**. No lead list, no lead detail, no inventory.

The reasoning is the same one behind the export restriction in
`SECURITY_MODEL.md`: none of it is needed to place a call, and a role that can
page through the lead book or the inventory can copy either. Under a threat
model of people who already hold legitimate accounts, access that adds no
capability is pure downside.

Enforced as capabilities (`contacts.browse`, `properties.read`) that the role
simply does not hold, so `/contacts` and `/properties` refuse it outright — the
missing nav items are a consequence, not the control. The queue endpoint
narrows its *response* to `{id, first_name, last_name, phone}`, so the rest
never leaves the server.

Still available to a Cold Caller: their queue, one-tap call logging,
temperature and remarks, escalation to the owner, and their own call history.

## Notes on enforcement

- This matrix must be implemented as query-layer scoping and endpoint-level authorization (see `SECURITY_MODEL.md`), not UI conditionals alone.
- "Team only" (Manager) rows depend on the `manager_id` relationship on `users` (see `DATA_MODEL.md`) and are a Phase 2 concern — Phase 1 can ship with just Owner/Agent/Cold Caller and no Manager role, collapsing "Team only" rows to "❌" until Phase 2.
- Cold Callers editing "limited fields" on a contact means they can add call remarks and update temperature/follow-up date, but cannot edit budget, location preferences, or reassign ownership — those remain Agent/Owner/Manager actions.
