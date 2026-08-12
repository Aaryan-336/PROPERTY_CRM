"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * Bottom sheet on mobile, centred panel on laptop.
 *
 * Fast-logging lives in here, so it opens from the bottom of the screen where
 * the thumb already is rather than from the top where the eye is.
 */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Every caller passes an inline arrow for onClose, so its identity changes on
  // each of their renders. Kept in a ref, the effect below can depend on `open`
  // alone — see the comment on the focus call for why that matters.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Once, as the sheet opens. This used to re-run on every parent render:
    // typing a character into a field re-rendered the caller, which produced a
    // fresh onClose, which re-ran this effect and pulled focus back to the
    // panel. One character in and the caret jumped out of the box.
    panelRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center lg:items-center">
      <button
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-ink/45 backdrop-blur-[2px]"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="animate-slide-up relative max-h-[92dvh] w-full overflow-y-auto rounded-t-card bg-parchment px-5 pb-8 pt-5 outline-none lg:max-w-lg lg:rounded-card lg:pb-6"
      >
        <div className="mx-auto mb-4 h-1 w-10 rounded-pill bg-hairline lg:hidden" />
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-xl leading-tight text-ink">{title}</h2>
            {subtitle && <p className="mt-1 text-sm text-slate">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="tap -mr-2 -mt-1 flex items-center justify-center rounded-full text-slate"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden>
              <path
                d="M18 6 6 18M6 6l12 12"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Large tap-to-select chips. Used instead of dropdowns wherever the option
 *  set is known and short — faster with one thumb, and no keyboard. */
export function ChipGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  columns = 2,
  allowClear = false,
}: {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T | null;
  onChange: (value: T | null) => void;
  columns?: 2 | 3;
  allowClear?: boolean;
}) {
  return (
    <fieldset>
      <legend className="mb-2 text-xs font-semibold text-slate">{label}</legend>
      <div
        className={`grid gap-2 ${columns === 3 ? "grid-cols-3" : "grid-cols-2"}`}
      >
        {options.map((option) => {
          const selected = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={selected}
              onClick={() =>
                onChange(selected && allowClear ? null : option.value)
              }
              className={`tap rounded-tile border px-3 py-2.5 text-sm font-semibold transition-colors ${
                selected
                  ? "border-ink bg-ink text-white"
                  : "border-hairline bg-card text-ink hover:border-sandstone"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
