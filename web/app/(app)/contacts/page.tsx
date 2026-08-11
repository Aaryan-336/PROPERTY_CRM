import Link from "next/link";

import { ContactRow } from "@/components/ContactRow";
import { FilterBar } from "@/components/FilterBar";
import { Pagination } from "@/components/Pagination";
import { PlusIcon } from "@/components/icons";
import { Card, EmptyState, STAGE_TONE, StatusPill } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { budgetRange, fullName, relativeTime, stageLabel } from "@/lib/format";
import { getCurrentUser } from "@/lib/session";
import { STAGES, type Contact, type Paged, type User } from "@/lib/types";

export const metadata = { title: "Leads · Balaji CRM" };

const SOURCES = [
  { value: "instagram", label: "Instagram" },
  { value: "walk_in", label: "Walk-in" },
  { value: "referral", label: "Referral" },
  { value: "portal", label: "Portal" },
  { value: "whatsapp_group", label: "WhatsApp" },
];

export default async function ContactsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const user = await getCurrentUser();
  const limit = 25;
  const offset = Number(params.offset ?? 0);

  const [contacts, staff] = await Promise.all([
    api<Paged<Contact>>(
      `/contacts${qs({
        limit,
        offset,
        q: params.q,
        stage: params.stage,
        source: params.source,
        owner_id: params.owner_id,
      })}`,
    ),
    user?.role === "owner" ? api<User[]>("/users") : Promise.resolve([]),
  ]);

  const selects = [
    { name: "stage", label: "Stage", options: STAGES },
    { name: "source", label: "Source", options: SOURCES },
    ...(user?.role === "owner"
      ? [
          {
            name: "owner_id",
            label: "Assigned to",
            options: staff.map((s) => ({
              value: String(s.id),
              label: s.name,
            })),
          },
        ]
      : []),
  ];

  return (
    <div>
      <header className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl leading-tight text-ink">Leads</h1>
          <p className="tabular mt-0.5 text-sm text-slate">
            {contacts.total} {user?.role === "owner" ? "firm-wide" : "assigned to you"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {user?.role === "owner" && (
            <a
              href="/api/crm/contacts/export"
              className="tap hidden items-center rounded-pill border border-hairline bg-card px-4 text-sm font-semibold text-ink lg:flex"
            >
              Export CSV
            </a>
          )}
          <Link
            href="/contacts/new"
            className="tap flex items-center gap-2 rounded-pill bg-ink px-4 text-sm font-semibold text-white"
          >
            <PlusIcon className="h-4 w-4" />
            <span className="hidden sm:inline">Add lead</span>
          </Link>
        </div>
      </header>

      <FilterBar searchPlaceholder="Search name or phone" selects={selects} />

      {contacts.items.length === 0 ? (
        <EmptyState
          title={
            params.q || params.stage || params.source
              ? "No leads match these filters. Try clearing them."
              : "No leads assigned yet — ask the owner to assign leads, or add one you sourced yourself."
          }
          action={
            <Link
              href="/contacts/new"
              className="tap inline-flex items-center rounded-pill bg-ink px-5 text-sm font-semibold text-white"
            >
              Add a lead
            </Link>
          }
        />
      ) : (
        <>
          {/* Mobile keeps the sparse card list; laptop switches to a real table
              with more columns, because a mouse and a big screen make density
              an advantage rather than a burden. */}
          <Card className="px-5 lg:hidden">
            <ul className="divide-y divide-hairline">
              {contacts.items.map((contact) => (
                <ContactRow key={contact.id} contact={contact} />
              ))}
            </ul>
          </Card>

          <Card className="hidden overflow-hidden lg:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-hairline bg-parchment text-left">
                  {["Name", "Phone", "Budget", "Locations", "Stage", "Owner", "Last activity"].map(
                    (heading) => (
                      <th
                        key={heading}
                        className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate"
                      >
                        {heading}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {contacts.items.map((contact) => (
                  <tr key={contact.id} className="hover:bg-parchment/60">
                    <td className="px-4 py-2.5">
                      <Link
                        href={`/contacts/${contact.id}`}
                        className="font-semibold text-ink hover:text-sandstone-deep"
                      >
                        {fullName(contact)}
                      </Link>
                    </td>
                    <td className="tabular px-4 py-2.5 text-slate">
                      {contact.phone ?? "—"}
                    </td>
                    <td className="tabular px-4 py-2.5 text-slate">
                      {budgetRange(contact.budget_min, contact.budget_max)}
                    </td>
                    <td className="max-w-[180px] truncate px-4 py-2.5 text-slate">
                      {contact.preferred_locations?.join(", ") || "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusPill
                        label={stageLabel(contact.stage)}
                        tone={STAGE_TONE[contact.stage ?? "new"] ?? "neutral"}
                      />
                    </td>
                    <td className="px-4 py-2.5 text-slate">
                      {contact.owner_name ?? "Unassigned"}
                    </td>
                    <td className="tabular px-4 py-2.5 text-slate">
                      {relativeTime(contact.last_activity_at ?? contact.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Pagination
            total={contacts.total}
            limit={contacts.limit}
            offset={contacts.offset}
          />
        </>
      )}
    </div>
  );
}
