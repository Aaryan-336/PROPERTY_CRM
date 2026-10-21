import type { ReactNode } from "react";

export const LEGAL_CONTACT_EMAIL = "balajirealtymalad@gmail.com";
export const LEGAL_UPDATED = "21 October 2026";

export function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="mx-auto max-w-2xl px-5 py-10 text-[15px] leading-relaxed">
      <h1 className="mb-1 text-3xl font-bold">{title}</h1>
      <p className="mb-8 text-sm opacity-60">Last updated {LEGAL_UPDATED}</p>
      <div className="space-y-4 [&_h2]:mt-8 [&_h2]:text-lg [&_h2]:font-semibold [&_ul]:ml-5 [&_ul]:list-disc [&_ul]:space-y-1">
        {children}
      </div>
    </main>
  );
}
