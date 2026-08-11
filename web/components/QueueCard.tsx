"use client";

import Link from "next/link";
import { useState } from "react";

import { LogCallSheet } from "@/components/LogCallSheet";
import { PhoneIcon } from "@/components/icons";
import { StatusPill, TEMPERATURE_TONE, type Tone } from "@/components/ui";
import { budgetRange, fullName, outcomeLabel, relativeTime } from "@/lib/format";
import type { QueueItem } from "@/lib/types";

const REASON_TONE: Record<number, Tone> = {
  1: "signal",
  2: "warning",
  3: "positive",
  4: "neutral",
};

/**
 * A lead in the calling queue.
 *
 * `featured` is the "next up" treatment: one obvious action, sized for a thumb,
 * with the reason it surfaced stated plainly so the caller trusts the order
 * rather than second-guessing it.
 */
export function QueueCard({
  item,
  featured = false,
}: {
  item: QueueItem;
  featured?: boolean;
}) {
  const [logging, setLogging] = useState(false);
  const contact = item.contact;
  const name = fullName(contact);

  if (!featured) {
    return (
      <>
        <div className="flex items-center gap-3 rounded-tile border border-hairline bg-card px-3.5 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-ink">{name}</p>
            <p className="tabular truncate text-xs text-slate">
              {contact.phone ?? "No phone"}
              {item.last_outcome ? ` · ${outcomeLabel(item.last_outcome)}` : ""}
            </p>
          </div>
          <StatusPill
            label={item.reason}
            tone={REASON_TONE[item.priority] ?? "neutral"}
          />
          <button
            onClick={() => setLogging(true)}
            aria-label={`Log call with ${name}`}
            className="tap flex shrink-0 items-center justify-center rounded-full bg-ink text-white"
          >
            <PhoneIcon className="h-4 w-4" />
          </button>
        </div>

        <LogCallSheet
          contactId={contact.id}
          contactName={name}
          phone={contact.contact_details_masked ? null : contact.phone}
          open={logging}
          onClose={() => setLogging(false)}
        />
      </>
    );
  }

  return (
    <>
      <div className="rounded-card border border-hairline bg-card p-5 shadow-card">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Link
              href={`/contacts/${contact.id}`}
              className="font-display block truncate text-xl leading-tight text-ink"
            >
              {name}
            </Link>
            <p className="tabular mt-1 text-sm text-slate">
              {contact.phone ?? "No phone on file"}
            </p>
          </div>
          <StatusPill
            label={item.reason}
            tone={REASON_TONE[item.priority] ?? "neutral"}
          />
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-hairline pt-4 text-sm">
          <div>
            <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate">
              Budget
            </dt>
            <dd className="tabular mt-0.5 text-ink">
              {budgetRange(contact.budget_min, contact.budget_max)}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate">
              Looking in
            </dt>
            <dd className="mt-0.5 truncate text-ink">
              {contact.preferred_locations?.join(", ") || "—"}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate">
              Last call
            </dt>
            <dd className="mt-0.5 text-ink">
              {item.last_called_at
                ? `${outcomeLabel(item.last_outcome)} · ${relativeTime(item.last_called_at)}`
                : "Never called"}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate">
              Temperature
            </dt>
            <dd className="mt-0.5">
              {item.last_temperature ? (
                <StatusPill
                  label={item.last_temperature.toUpperCase()}
                  tone={TEMPERATURE_TONE[item.last_temperature] ?? "neutral"}
                />
              ) : (
                <span className="text-ink">—</span>
              )}
            </dd>
          </div>
        </dl>

        {/* The single most common action, in the bottom third where the thumb is. */}
        <button
          onClick={() => setLogging(true)}
          className="tap mt-5 flex w-full items-center justify-center gap-2 rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white"
        >
          <PhoneIcon className="h-[18px] w-[18px]" />
          Call &amp; log
        </button>
      </div>

      <LogCallSheet
        contactId={contact.id}
        contactName={name}
        phone={contact.contact_details_masked ? null : contact.phone}
        open={logging}
        onClose={() => setLogging(false)}
      />
    </>
  );
}
