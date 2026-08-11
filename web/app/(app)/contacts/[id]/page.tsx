import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ContactActions } from "@/components/ContactActions";
import { LeadJourney } from "@/components/LeadJourney";
import { MatchedInventory } from "@/components/MatchedInventory";
import { ShowingsTimeline } from "@/components/ShowingsTimeline";
import {
  Card,
  InkCard,
  MaskedHint,
  SectionHeading,
  STAGE_TONE,
  StatusPill,
} from "@/components/ui";
import { ApiRequestError, api, apiOptional, qs } from "@/lib/api";
import { budgetRange, fullName, relativeTime, stageLabel, titleCase } from "@/lib/format";
import { getCurrentUser } from "@/lib/session";
import type {
  Activity,
  CallLog,
  Contact,
  Paged,
  PropertyMatch,
  Showing,
  Task,
} from "@/lib/types";

export default async function ContactDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await getCurrentUser();
  // Cold Callers have no access to the lead book or the inventory — the API
  // refuses both for this role. This redirect is a courtesy so a stale link or
  // a bookmark lands somewhere useful rather than on an error.
  if (user?.role === "cold_caller") redirect("/queue");

  let contact: Contact;
  try {
    contact = await api<Contact>(`/contacts/${id}`);
  } catch (error) {
    // A lead outside the caller's scope is indistinguishable from one that
    // does not exist — the backend returns the same 404 either way.
    if (error instanceof ApiRequestError && error.status === 404) notFound();
    throw error;
  }

  const [calls, activities, showings, tasks, matches] = await Promise.all([
    api<Paged<CallLog>>(`/calls${qs({ contact_id: id, limit: 50 })}`),
    api<Paged<Activity>>(`/activities${qs({ contact_id: id, limit: 50 })}`),
    api<Paged<Showing>>(`/property-interests${qs({ contact_id: id, limit: 50 })}`),
    api<Paged<Task>>(`/tasks${qs({ contact_id: id, status: "pending", limit: 20 })}`),
    // apiOptional so a future permission change hides the panel rather than
    // breaking the page. Cold Callers never reach here — they are redirected
    // above and the API refuses them anyway.
    apiOptional<PropertyMatch[]>(`/contacts/${id}/matches${qs({ limit: 6 })}`),
  ]);

  const name = fullName(contact);
  const canShowProperty = user?.role === "owner" || user?.role === "agent";

  return (
    <div className="space-y-5 pb-4">
      <Link
        href="/contacts"
        className="inline-flex items-center gap-1 text-xs font-semibold text-slate"
      >
        ← Leads
      </Link>

      <InkCard className="p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="font-display text-2xl leading-tight text-white lg:text-3xl">
              {name}
            </h1>
            <p className="tabular mt-1.5 text-sm text-ink-dim">
              {contact.phone ?? "No phone on file"}
            </p>
            {contact.contact_details_masked && (
              <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-muted">
                <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" aria-hidden>
                  <path
                    d="M12 15v2m-6 4h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2Zm10-10V7a4 4 0 0 0-8 0v4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                Full number unlocks once you log your first call with this lead.
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusPill
              label={stageLabel(contact.stage)}
              tone={STAGE_TONE[contact.stage ?? "new"] ?? "neutral"}
            />
            {contact.owner_name && (
              <span className="text-xs text-ink-muted">
                Assigned to {contact.owner_name}
              </span>
            )}
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-ink-line pt-4 lg:grid-cols-4">
          <Detail label="Budget" value={budgetRange(contact.budget_min, contact.budget_max)} mono />
          <Detail
            label="Preferred areas"
            value={contact.preferred_locations?.join(", ") || "—"}
          />
          <Detail
            label="Looking for"
            value={
              contact.property_type_interest
                ? titleCase(contact.property_type_interest)
                : "—"
            }
          />
          <Detail
            label="Buyer type"
            value={contact.buyer_type ? titleCase(contact.buyer_type) : "—"}
          />
          <Detail
            label="Source"
            value={contact.lead_source ? titleCase(contact.lead_source) : "—"}
          />
          <Detail label="Added" value={relativeTime(contact.created_at)} mono />
          <Detail
            label="Last activity"
            value={relativeTime(contact.last_activity_at ?? contact.updated_at)}
            mono
          />
          <Detail label="Calls logged" value={String(calls.total)} mono />
        </dl>
      </InkCard>

      <div className="grid gap-5 [&>*]:min-w-0 lg:grid-cols-[1fr_360px]">
        <Card className="p-5">
          <SectionHeading
            title="Journey"
            hint="Every call, visit and stage change on this lead"
          />
          {/* The same timeline component as the owner's feed and the property
              history — one visual language for "who did what when". */}
          <LeadJourney
            contact={contact}
            calls={calls.items}
            activities={activities.items}
            tasks={tasks.items}
          />
        </Card>

        {/* Suggestions sit in the main column, under the journey: an agent
            reads what has happened, then what to show next. */}
        {matches && (
          <div className="lg:col-start-1">
            <MatchedInventory matches={matches} />
          </div>
        )}

        <div className="space-y-5">
          {contact.email && (
            <Card className="p-5">
              <SectionHeading title="Contact" />
              <p className="tabular break-all text-sm text-ink">{contact.email}</p>
              {contact.contact_details_masked && (
                <p className="mt-2">
                  <MaskedHint>Partly hidden until you log an interaction</MaskedHint>
                </p>
              )}
            </Card>
          )}

          {canShowProperty && (
            <Card className="p-5">
              <SectionHeading
                title="Properties shown"
                hint={`${showings.total} logged`}
              />
              <ShowingsTimeline showings={showings.items.slice(0, 6)} hideAgent />
            </Card>
          )}

          {tasks.items.length > 0 && (
            <Card className="p-5">
              <SectionHeading title="Open follow-ups" />
              <ul className="space-y-2">
                {tasks.items.map((task) => (
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
        </div>
      </div>

      {/* Primary actions pinned above the mobile nav pill — thumb territory. */}
      <ContactActions
        contactId={contact.id}
        contactName={name}
        phone={contact.contact_details_masked ? null : contact.phone}
        canLogShowing={canShowProperty}
      />
    </div>
  );
}

function Detail({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
        {label}
      </dt>
      <dd className={`mt-1 text-sm text-white ${mono ? "tabular" : ""}`}>{value}</dd>
    </div>
  );
}
