import Link from "next/link";

import { ContactRow } from "@/components/ContactRow";
import { ChevronRight, PlusIcon } from "@/components/icons";
import {
  Card,
  EmptyState,
  InkCard,
  MetricTile,
  SectionHeading,
  StatusPill,
} from "@/components/ui";
import { api } from "@/lib/api";
import { money, relativeTime } from "@/lib/format";
import type { Paged, Contact, Property, Showing, Task, User } from "@/lib/types";

/** Agent home: today's scheduled site visits, then the assigned leads queue. */
export async function AgentHome({ user }: { user: User }) {
  const [leads, tasks, showings, fresh] = await Promise.all([
    api<Paged<Contact>>("/contacts?limit=50"),
    api<Paged<Task>>("/tasks?status=pending&limit=50"),
    api<Paged<Showing>>("/property-interests?limit=50"),
    // The WhatsApp feed adds inventory continuously. An agent who does not see
    // what arrived overnight is still working yesterday's stock.
    api<Paged<Property>>("/properties?status=available&limit=6"),
  ]);

  const now = Date.now();
  const overdue = tasks.items.filter(
    (t) => t.due_at && new Date(t.due_at).getTime() <= now,
  );
  const upcoming = tasks.items.filter(
    (t) => !t.due_at || new Date(t.due_at).getTime() > now,
  );

  const scheduled = leads.items.filter(
    (c) => c.stage === "site_visit_scheduled",
  );
  const active = leads.items.filter(
    (c) => !["closed", "lost"].includes(c.stage ?? ""),
  );

  return (
    <div className="space-y-5">
      <InkCard className="p-5 lg:p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
          {new Date().toLocaleDateString("en-IN", {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
        <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
          {user.name.split(" ")[0]}&rsquo;s day
        </h1>

        <div className="mt-5 grid grid-cols-3 gap-2.5">
          <MetricTile label="Active leads" value={active.length} ink />
          <MetricTile label="Visits set" value={scheduled.length} ink />
          <MetricTile
            label="Follow-ups"
            value={tasks.total}
            sub={overdue.length ? `${overdue.length} overdue` : "on track"}
            ink
          />
        </div>
      </InkCard>

      {overdue.length > 0 && (
        <Card className="border-signal/40 p-5">
          <SectionHeading
            title="Overdue follow-ups"
            hint="You promised these already"
            action={<StatusPill label={`${overdue.length}`} tone="signal" />}
          />
          <ul className="space-y-2">
            {overdue.slice(0, 4).map((task) => (
              <li key={task.id}>
                <Link
                  href={`/contacts/${task.contact_id}`}
                  className="flex items-center justify-between gap-3 rounded-tile bg-signal-soft px-3.5 py-3"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-ink">
                      {task.title}
                    </span>
                    <span className="tabular block text-xs text-signal">
                      due {relativeTime(task.due_at)}
                    </span>
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-signal" />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-5 [&>*]:min-w-0 lg:grid-cols-[1fr_360px]">
        <Card className="p-5">
          <SectionHeading
            title="Site visits scheduled"
            hint="Leads waiting on a viewing"
            action={
              <Link
                href="/contacts?stage=site_visit_scheduled"
                className="flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
              >
                See all
                <ChevronRight className="h-3.5 w-3.5" />
              </Link>
            }
          />
          {scheduled.length === 0 ? (
            <EmptyState
              title="No visits scheduled. Open a lead and log a showing once you've set one up."
              action={
                <Link
                  href="/contacts"
                  className="tap inline-flex items-center rounded-pill bg-ink px-5 text-sm font-semibold text-white"
                >
                  Open my leads
                </Link>
              }
            />
          ) : (
            <ul className="divide-y divide-hairline">
              {scheduled.slice(0, 5).map((contact) => (
                <ContactRow key={contact.id} contact={contact} />
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-5">
          <Card className="p-5">
            <SectionHeading
              title="My leads"
              hint={`${leads.total} assigned to you`}
              action={
                <Link
                  href="/contacts/new"
                  aria-label="Add lead"
                  className="tap flex items-center justify-center rounded-full bg-sandstone text-white"
                >
                  <PlusIcon className="h-4 w-4" />
                </Link>
              }
            />
            {active.length === 0 ? (
              <EmptyState title="No leads assigned yet — ask the owner to assign leads, or add one you sourced yourself." />
            ) : (
              <ul className="divide-y divide-hairline">
                {active.slice(0, 6).map((contact) => (
                  <ContactRow key={contact.id} contact={contact} compact />
                ))}
              </ul>
            )}
          </Card>

          {upcoming.length > 0 && (
            <Card className="p-5">
              <SectionHeading title="Coming up" hint="Scheduled follow-ups" />
              <ul className="space-y-2">
                {upcoming.slice(0, 4).map((task) => (
                  <li
                    key={task.id}
                    className="flex items-center justify-between gap-3 rounded-tile bg-parchment px-3.5 py-2.5"
                  >
                    <span className="min-w-0 truncate text-sm text-ink">
                      {task.title}
                    </span>
                    <span className="tabular shrink-0 text-xs text-slate">
                      {relativeTime(task.due_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="p-5">
            <SectionHeading
              title="New inventory"
              hint="Latest listings, including from WhatsApp"
              action={
                <Link
                  href="/properties"
                  className="flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
                >
                  Browse
                  <ChevronRight className="h-3.5 w-3.5" />
                </Link>
              }
            />
            {fresh.items.length === 0 ? (
              <EmptyState title="No available listings yet." />
            ) : (
              <ul className="divide-y divide-hairline">
                {fresh.items.slice(0, 5).map((property) => (
                  <li key={property.id}>
                    <Link
                      href={`/properties/${property.id}`}
                      className="flex items-center justify-between gap-3 py-2.5"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-ink">
                          {property.bhk !== null ? `${property.bhk}BHK · ` : ""}
                          {property.building ?? property.location}
                        </span>
                        <span className="tabular block truncate text-[11px] text-slate">
                          {money(property.price)}
                          {property.listing_type === "rent" ? " / month" : ""}
                          {property.source === "whatsapp_group"
                            ? ` · ${property.source_group ?? "WhatsApp"}`
                            : ""}
                        </span>
                      </span>
                      <span className="tabular shrink-0 text-[11px] text-slate">
                        {relativeTime(property.last_seen_at ?? property.created_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="p-5">
            <SectionHeading title="My showings" hint="Properties you've shown" />
            <p className="tabular font-display text-3xl text-ink">
              {showings.total}
            </p>
            <p className="mt-1 text-xs text-slate">
              Logged under your name and visible to the owner.
            </p>
            <Link
              href="/showings"
              className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
            >
              View timeline
              <ChevronRight className="h-3.5 w-3.5" />
            </Link>
          </Card>
        </div>
      </div>
    </div>
  );
}
