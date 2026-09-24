import type { ReactNode } from "react";

/** The input look every form in the app uses (see NewContactForm). */
export const inputClass =
  "tap w-full rounded-tile border border-hairline bg-card px-4 text-[16px] text-ink outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft";

/** Full-width primary action, as on the lead and listing forms. */
export const primaryButtonClass =
  "press tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50";

export function Field({
  label,
  required = false,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate">
        {label}
        {required && <span className="text-signal"> *</span>}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-[11px] text-slate">{hint}</span>}
    </label>
  );
}
