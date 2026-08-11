import { FeedStream } from "@/components/FeedStream";
import { Card, EmptyState } from "@/components/ui";
import { api } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import type { FeedItem } from "@/lib/types";

export const metadata = { title: "Activity · Balaji CRM" };

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<{ hours?: string }>;
}) {
  const { hours } = await searchParams;
  const since = Number(hours ?? 168);
  const user = await getCurrentUser();

  const feed = await api<FeedItem[]>(
    `/activities/feed?limit=50&since_hours=${since}`,
  );

  const ranges = [
    { hours: 24, label: "24 hours" },
    { hours: 72, label: "3 days" },
    { hours: 168, label: "7 days" },
    { hours: 720, label: "30 days" },
  ];

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-4">
        <h1 className="font-display text-2xl leading-tight text-ink">
          Live activity
        </h1>
        <p className="mt-0.5 text-sm text-slate">
          {user?.role === "owner"
            ? "Every call, site visit and stage change across the firm."
            : "Everything you've logged."}
        </p>
      </header>

      <div className="no-scrollbar mb-4 flex gap-2 overflow-x-auto">
        {ranges.map((range) => (
          <a
            key={range.hours}
            href={`/feed?hours=${range.hours}`}
            className={`tap flex shrink-0 items-center rounded-pill border px-4 text-sm font-semibold ${
              since === range.hours
                ? "border-ink bg-ink text-white"
                : "border-hairline bg-card text-ink"
            }`}
          >
            {range.label}
          </a>
        ))}
      </div>

      {feed.length === 0 ? (
        <EmptyState title="Nothing logged in this period. Try a longer range." />
      ) : (
        <Card className="p-5">
          <FeedStream items={feed} />
        </Card>
      )}
    </div>
  );
}
