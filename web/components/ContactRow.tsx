import Link from "next/link";

import { ChevronRight } from "@/components/icons";
import { STAGE_TONE, StatusPill } from "@/components/ui";
import { budgetRange, fullName, relativeTime, stageLabel } from "@/lib/format";
import type { Contact } from "@/lib/types";

/** Mobile-first lead row. The laptop view uses a real table instead (ContactTable). */
export function ContactRow({
  contact,
  compact = false,
}: {
  contact: Contact;
  compact?: boolean;
}) {
  return (
    <li>
      <Link
        href={`/contacts/${contact.id}`}
        className="flex items-center gap-3 py-3 transition-opacity hover:opacity-80"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-[15px] font-semibold text-ink">
              {fullName(contact)}
            </p>
            {contact.contact_details_masked && (
              <span
                title="Phone hidden until you log an interaction"
                className="shrink-0 text-slate"
              >
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
              </span>
            )}
          </div>

          <p className="tabular mt-0.5 truncate text-xs text-slate">
            {contact.phone ?? "No phone"}
            {!compact && (
              <>
                {" · "}
                {budgetRange(contact.budget_min, contact.budget_max)}
              </>
            )}
          </p>

          {!compact && contact.preferred_locations?.length ? (
            <p className="mt-0.5 truncate text-xs text-slate">
              {contact.preferred_locations.join(", ")}
            </p>
          ) : null}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <StatusPill
            label={stageLabel(contact.stage)}
            tone={STAGE_TONE[contact.stage ?? "new"] ?? "neutral"}
          />
          <span className="tabular text-[11px] text-slate">
            {relativeTime(contact.last_activity_at ?? contact.updated_at)}
          </span>
        </div>

        <ChevronRight className="h-4 w-4 shrink-0 text-slate opacity-50" />
      </Link>
    </li>
  );
}
