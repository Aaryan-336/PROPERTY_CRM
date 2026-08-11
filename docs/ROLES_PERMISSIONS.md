# Roles & Permissions Matrix — Real Estate Broker CRM

## Roles

- **Owner** — firm head, full visibility and control
- **Manager** — oversees a sub-team (Phase 2), scoped version of Owner's oversight powers
- **Agent** — closing/field agent, works assigned leads
- **Cold Caller** — calling team, works a call queue

## Permission matrix

| Capability | Owner | Manager | Agent | Cold Caller |
|---|:---:|:---:|:---:|:---:|
| View all contacts (firm-wide) | ✅ | Team only | ❌ (own only) | ❌ (assigned queue only) |
| View own assigned contacts | ✅ | ✅ | ✅ | ✅ |
| Create/edit contacts | ✅ | ✅ | ✅ (own only) | ✅ (limited fields — remarks) |
| Delete contacts (soft delete) | ✅ | ✅ | ❌ | ❌ |
| Bulk export contacts | ✅ | ✅ (own team) | ❌ | ❌ |
| View full phone/email (unmasked) | ✅ | ✅ | Only after first logged interaction | Only for assigned queue leads |
| Reassign lead ownership | ✅ | ✅ (own team) | ❌ (request only) | ❌ |
| View all properties/inventory | ✅ | ✅ | ✅ | ✅ (view only) |
| Add/edit property listings | ✅ | ✅ | ✅ | ❌ |
| View firm-wide activity feed | ✅ | Team only | ❌ (own activity only) | ❌ (own activity only) |
| View "who showed what to whom" | ✅ | Team only | Own records only | ❌ |
| View team performance dashboard | ✅ | Team only | ❌ | ❌ |
| Log a call | ✅ | ✅ | ✅ | ✅ |
| Flag/escalate to owner | ✅ (receives) | ✅ (receives, team) | ✅ (can flag) | ✅ (can flag) |
| View audit log | ✅ (full) | ✅ (team) | ❌ | ❌ |
| Manage users/roles | ✅ | ❌ | ❌ | ❌ |
| Configure WhatsApp ingestion groups | ✅ | ❌ | ❌ | ❌ |

## Notes on enforcement

- This matrix must be implemented as query-layer scoping and endpoint-level authorization (see `SECURITY_MODEL.md`), not UI conditionals alone.
- "Team only" (Manager) rows depend on the `manager_id` relationship on `users` (see `DATA_MODEL.md`) and are a Phase 2 concern — Phase 1 can ship with just Owner/Agent/Cold Caller and no Manager role, collapsing "Team only" rows to "❌" until Phase 2.
- Cold Callers editing "limited fields" on a contact means they can add call remarks and update temperature/follow-up date, but cannot edit budget, location preferences, or reassign ownership — those remain Agent/Owner/Manager actions.
