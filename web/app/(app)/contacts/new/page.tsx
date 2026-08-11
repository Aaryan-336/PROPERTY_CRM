import Link from "next/link";

import { NewContactForm } from "@/components/NewContactForm";

export const metadata = { title: "Add lead · Balaji CRM" };

export default function NewContactPage() {
  return (
    <div className="mx-auto max-w-lg">
      <Link
        href="/contacts"
        className="inline-flex items-center gap-1 text-xs font-semibold text-slate"
      >
        ← Leads
      </Link>
      <h1 className="font-display mt-2 text-2xl leading-tight text-ink">Add a lead</h1>
      <p className="mt-1 text-sm text-slate">
        This lead will be assigned to you and appear in your queue.
      </p>

      <div className="mt-5">
        <NewContactForm />
      </div>
    </div>
  );
}
