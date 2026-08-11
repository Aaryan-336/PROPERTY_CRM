import { PhoneIcon } from "@/components/icons";
import { Card, StatusPill } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import type { QueueItem } from "@/lib/types";

/**
 * One lead in the calling queue: who to ring, and on what number.
 *
 * Deliberately nothing else. A cold caller's job is the call, and budget,
 * preferred areas, stage and temperature are not needed to place one — so the
 * queue does not carry them. That is enforced server-side (the endpoint
 * returns only these four fields; see schemas.QueueContact), and this card
 * simply has nothing more to render.
 *
 * The `reason` label stays because it is about the *call*, not the client:
 * without it the queue's order looks arbitrary and a caller cannot tell an
 * overdue promise from a routine touch.
 */
export function QueueCard({
  item,
  featured = false,
}: {
  item: QueueItem;
  featured?: boolean;
}) {
  const { contact } = item;
  const name = `${contact.first_name} ${contact.last_name ?? ""}`.trim();
  const dialable = contact.phone?.replace(/[^\d+]/g, "");
  const overdue = item.priority === 1;

  if (!featured) {
    return (
      <Card className="flex items-center justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{name}</p>
          <p className="tabular truncate text-xs text-slate">
            {contact.phone ?? "No number"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {overdue && <StatusPill label="Overdue" tone="signal" />}
          {dialable && (
            <a
              href={`tel:${dialable}`}
              aria-label={`Call ${name}`}
              className="tap flex items-center justify-center rounded-full bg-ink text-white"
            >
              <PhoneIcon className="h-4 w-4" />
            </a>
          )}
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-display truncate text-xl leading-tight text-ink">
            {name}
          </h2>
          <p className="tabular mt-1 truncate text-sm text-slate">
            {contact.phone ?? "No number on this lead"}
          </p>
        </div>
        <StatusPill
          label={item.reason}
          tone={overdue ? "signal" : "neutral"}
        />
      </div>

      {item.due_at && (
        <p className="tabular mt-2 text-xs text-slate">
          Callback due {relativeTime(item.due_at)}
        </p>
      )}

      {dialable ? (
        <a
          href={`tel:${dialable}`}
          className="tap mt-4 flex items-center justify-center gap-2 rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white"
        >
          <PhoneIcon className="h-5 w-5" />
          Call &amp; log
        </a>
      ) : (
        <p className="mt-4 rounded-tile bg-parchment-deep px-4 py-3 text-center text-sm text-slate">
          No phone number on this lead.
        </p>
      )}
    </Card>
  );
}
