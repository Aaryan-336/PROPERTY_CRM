import { FilterBar } from "@/components/FilterBar";
import { Pagination } from "@/components/Pagination";
import { ShieldIcon } from "@/components/icons";
import { Avatar, Card, EmptyState, StatusPill, type Tone } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { clockTime, dayStamp, relativeTime, titleCase } from "@/lib/format";
import type { AuditEntry, Paged, User } from "@/lib/types";

export const metadata = { title: "Audit log · Balaji CRM" };

const ACTION_TONE: Record<string, Tone> = {
  view: "neutral",
  create: "positive",
  edit: "warning",
  delete: "signal",
  export: "signal",
  reassign: "sand",
  import: "warning",
};

/**
 * Owner-only, read-only view of the audit trail.
 *
 * There is deliberately no edit or delete control anywhere on this page —
 * and no endpoint behind one either. The application's database role has no
 * UPDATE or DELETE grant on this table, so the history cannot be rewritten
 * even by the owner.
 */
export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const limit = 50;
  const offset = Number(params.offset ?? 0);

  const [entries, staff] = await Promise.all([
    api<Paged<AuditEntry>>(
      `/audit-log${qs({
        limit,
        offset,
        user_id: params.user_id,
        resource_type: params.resource_type,
        action: params.action,
      })}`,
    ),
    api<User[]>("/users"),
  ]);

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-4">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-teal-soft text-teal">
            <ShieldIcon className="h-4 w-4" />
          </span>
          <h1 className="font-display text-2xl leading-tight text-ink">Audit log</h1>
        </div>
        <p className="tabular mt-1 text-sm text-slate">
          {entries.total} entries · append-only, retained after deletion
        </p>
      </header>

      <FilterBar
        showSearch={false}
        selects={[
          {
            name: "user_id",
            label: "Staff member",
            options: staff.map((s) => ({ value: String(s.id), label: s.name })),
          },
          {
            name: "action",
            label: "Action",
            options: [
              { value: "view", label: "View" },
              { value: "create", label: "Create" },
              { value: "edit", label: "Edit" },
              { value: "export", label: "Export" },
              { value: "reassign", label: "Reassign" },
              { value: "delete", label: "Delete" },
            ],
          },
          {
            name: "resource_type",
            label: "Resource",
            options: [
              { value: "contact", label: "Contacts" },
              { value: "property", label: "Properties" },
              { value: "call_log", label: "Calls" },
              { value: "property_interest", label: "Showings" },
            ],
          },
        ]}
      />

      {entries.items.length === 0 ? (
        <EmptyState title="No audit entries match these filters." />
      ) : (
        <>
          <Card className="overflow-hidden">
            <ul className="divide-y divide-hairline">
              {entries.items.map((entry) => (
                <li key={entry.id} className="flex items-start gap-3 px-4 py-3">
                  <Avatar name={entry.user_name} id={entry.user_id} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-ink">
                        {entry.user_name ?? `User ${entry.user_id}`}
                      </span>
                      <StatusPill
                        label={titleCase(entry.action)}
                        tone={ACTION_TONE[entry.action] ?? "neutral"}
                      />
                      <span className="text-xs text-slate">
                        {titleCase(entry.resource_type)}
                        {entry.resource_id ? ` #${entry.resource_id}` : ""}
                      </span>
                    </div>
                    <p className="tabular mt-1 truncate text-xs text-slate">
                      {summarize(entry)}
                    </p>
                  </div>
                  <time
                    dateTime={entry.occurred_at}
                    title={`${dayStamp(entry.occurred_at)} ${clockTime(entry.occurred_at)}`}
                    className="tabular shrink-0 text-[11px] text-slate"
                  >
                    {relativeTime(entry.occurred_at)}
                  </time>
                </li>
              ))}
            </ul>
          </Card>

          <Pagination
            total={entries.total}
            limit={entries.limit}
            offset={entries.offset}
          />
        </>
      )}
    </div>
  );
}

function summarize(entry: AuditEntry): string {
  const detail = entry.detail ?? {};
  const parts: string[] = [];

  if (typeof detail.exported_count === "number") {
    parts.push(`${detail.exported_count} rows exported`);
  }
  if (typeof detail.returned_count === "number") {
    parts.push(`${detail.returned_count} records returned`);
  }
  if (detail.changed_fields && typeof detail.changed_fields === "object") {
    parts.push(
      `changed ${Object.keys(detail.changed_fields as object).join(", ")}`,
    );
  }
  if (detail.old_owner_id && detail.new_owner_id) {
    parts.push(`owner ${detail.old_owner_id} → ${detail.new_owner_id}`);
  }
  if (detail.outcome) parts.push(String(detail.outcome).replace(/_/g, " "));
  if (detail.forced_over_duplicates) parts.push("created over a duplicate warning");
  if (detail.sessions_revoked) parts.push(`${detail.sessions_revoked} sessions revoked`);

  const status = typeof detail.status === "number" ? detail.status : null;
  // A run of 403s or 404s under one name is what an insider probing for other
  // people's leads looks like, so the status is never hidden.
  if (status && status >= 400) parts.push(`denied (${status})`);

  if (parts.length === 0 && detail.path) parts.push(String(detail.path));
  return parts.join(" · ") || "—";
}
