import { Card, EmptyState, SectionHeading, StatusPill } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import type { BatchPerformance } from "@/lib/types";

/**
 * Every uploaded calling list, as a card, ranked by what it produced.
 *
 * The owner buys these lists and the only question afterwards is which ones
 * were worth the money. That makes comparison the whole design: same figures,
 * same order, on one screen. A per-list detail page would answer a question
 * nobody is asking.
 *
 * Cards rather than a table because the interesting content is a progress
 * story — how much of the list has been worked, and what came out — which
 * reads better as a bar than as two more numeric columns.
 */
export function DatabaseCards({ batches }: { batches: BatchPerformance[] }) {
  if (batches.length === 0) {
    return (
      <div>
        <SectionHeading title="Databases" hint="Uploaded calling lists" />
        <EmptyState title="No databases yet. Upload a spreadsheet above and it will appear here with its numbers." />
      </div>
    );
  }

  // Best first, but only among lists that have actually been worked. An
  // untouched upload has no conversion rate to rank on and would otherwise
  // sort as if it had failed.
  const ranked = [...batches].sort((a, b) => {
    const ac = a.conversion_rate ?? -1;
    const bc = b.conversion_rate ?? -1;
    if (ac !== bc) return bc - ac;
    return b.size - a.size;
  });

  const totalLeads = batches.reduce((n, b) => n + b.leads, 0);
  const totalNumbers = batches.reduce((n, b) => n + b.size, 0);

  return (
    <div>
      <SectionHeading
        title="Databases"
        hint={`${batches.length} list${batches.length === 1 ? "" : "s"} · ${totalNumbers} numbers · ${totalLeads} became leads`}
      />
      <div className="grid gap-3 lg:grid-cols-2 [&>*]:min-w-0">
        {ranked.map((b) => (
          <DatabaseCard key={b.id} batch={b} />
        ))}
      </div>
    </div>
  );
}

function DatabaseCard({ batch: b }: { batch: BatchPerformance }) {
  const pct = (v: number | null) =>
    v === null ? "—" : `${Math.round(v * 100)}%`;

  const worked = b.size ? (b.called / b.size) * 100 : 0;
  const started = b.called > 0;

  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{b.name}</p>
          <p className="mt-0.5 truncate text-[11px] text-slate">
            {b.size} numbers
            {b.uploaded_by ? ` · ${b.uploaded_by}` : ""} ·{" "}
            {relativeTime(b.created_at)}
          </p>
        </div>
        {started ? (
          <Verdict rate={b.conversion_rate} />
        ) : (
          <StatusPill label="Not started" tone="neutral" />
        )}
      </div>

      {/* How much of the list has been worked. Without this, a low conversion
          rate is unreadable — it could be a bad list or an untouched one. */}
      <div className="mt-3.5">
        <div className="mb-1 flex items-center justify-between text-[11px] text-slate">
          <span>
            {b.called} of {b.size} called
          </span>
          <span className="tabular">{pct(b.contact_rate)}</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-pill bg-parchment-deep">
          <div
            className="h-full rounded-pill bg-sandstone"
            style={{ width: `${worked}%` }}
          />
        </div>
      </div>

      <dl className="mt-3.5 grid grid-cols-4 gap-2 border-t border-hairline pt-3">
        <Stat label="Reached" value={b.reached} />
        <Stat label="Leads" value={b.leads} accent={b.leads > 0} />
        <Stat label="Visits" value={b.showings} />
        <Stat label="Closed" value={b.closed} />
      </dl>

      <p className="mt-3 text-[11px] leading-relaxed text-slate">
        {started ? (
          <>
            <span className="font-semibold text-ink">{pct(b.conversion_rate)}</span>{" "}
            of the numbers called became leads
            {b.reach_rate !== null && (
              <> · {pct(b.reach_rate)} of calls actually reached someone</>
            )}
            {b.uncalled > 0 && <> · {b.uncalled} still to call</>}
          </>
        ) : (
          "Nobody has called from this list yet."
        )}
      </p>

      {/* Dirt in the file itself, which is a property of the vendor rather
          than of anyone's calling. Only worth the line when there was some. */}
      {(b.duplicate_rows > 0 || b.invalid_rows > 0) && (
        <p className="mt-1.5 text-[11px] text-slate">
          On upload: {b.total_rows} rows, {b.duplicate_rows} already known,{" "}
          {b.invalid_rows} unusable.
        </p>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-3 text-[11px] text-slate">
        {b.assigned_to.length > 0 ? (
          <span className="truncate">With {b.assigned_to.join(", ")}</span>
        ) : (
          <span>Unassigned</span>
        )}
        {b.last_activity_at && (
          <span>· last call {relativeTime(b.last_activity_at)}</span>
        )}
      </div>
    </Card>
  );
}

/**
 * A plain-language read on the conversion rate.
 *
 * The owner should not have to hold a benchmark in their head to know whether
 * 4% is good. Thresholds are for cold calling off a bought list, where a few
 * percent is a genuinely working list — they are intentionally not the numbers
 * you would use for inbound enquiries.
 */
function Verdict({ rate }: { rate: number | null }) {
  if (rate === null) return <StatusPill label="No calls yet" tone="neutral" />;
  if (rate >= 0.05) return <StatusPill label="Performing" tone="positive" />;
  if (rate >= 0.02) return <StatusPill label="Steady" tone="warning" />;
  return <StatusPill label="Weak" tone="signal" />;
}

function Stat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate">
        {label}
      </dt>
      <dd
        className={`tabular font-display text-lg leading-none ${
          accent ? "text-sandstone-deep" : "text-ink"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
