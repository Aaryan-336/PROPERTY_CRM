import { ShowingsTimeline } from "@/components/ShowingsTimeline";
import { Pagination } from "@/components/Pagination";
import { Card, EmptyState } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import type { Paged, Showing, User } from "@/lib/types";
import { ShowingsFilter } from "@/components/ShowingsFilter";

export const metadata = { title: "Who showed what · Balaji CRM" };

/**
 * The owner's core visibility feature: who showed which property to which
 * client, and when — filterable by any of the three, rendered as the Journey
 * Timeline rather than a raw table.
 *
 * An Agent opening this page sees only their own showings; the filter controls
 * narrow that set and cannot widen it, because the backend query is already
 * scoped before any filter is applied.
 */
export default async function ShowingsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const user = await getCurrentUser();
  const limit = 25;
  const offset = Number(params.offset ?? 0);

  const [showings, staff] = await Promise.all([
    api<Paged<Showing>>(
      `/property-interests${qs({
        limit,
        offset,
        agent_id: params.agent_id,
        contact_id: params.contact_id,
        property_id: params.property_id,
      })}`,
    ),
    user?.role === "owner" ? api<User[]>("/users") : Promise.resolve([]),
  ]);

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-4">
        <h1 className="font-display text-2xl leading-tight text-ink">
          Who showed what to whom
        </h1>
        <p className="tabular mt-0.5 text-sm text-slate">
          {showings.total} showings
          {user?.role === "owner" ? " across the firm" : " logged by you"}
        </p>
      </header>

      {user?.role === "owner" && (
        <ShowingsFilter
          agents={staff.filter((s) => s.role === "agent" || s.role === "owner")}
        />
      )}

      {showings.items.length === 0 ? (
        <EmptyState title="No showings logged for this filter. Agents log these from a lead's page after a viewing." />
      ) : (
        <>
          <Card className="p-5">
            <ShowingsTimeline showings={showings.items} />
          </Card>
          <Pagination
            total={showings.total}
            limit={showings.limit}
            offset={showings.offset}
          />
        </>
      )}
    </div>
  );
}
