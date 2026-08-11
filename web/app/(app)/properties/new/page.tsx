import Link from "next/link";
import { redirect } from "next/navigation";

import { NewPropertyForm } from "@/components/NewPropertyForm";
import { getCurrentUser } from "@/lib/session";

export const metadata = { title: "Add listing · Balaji CRM" };

export default async function NewPropertyPage() {
  const user = await getCurrentUser();
  // Cold callers may read inventory but not add to it. The backend refuses the
  // write regardless; this just avoids showing a form that would fail.
  if (user && user.role !== "owner" && user.role !== "agent") redirect("/properties");

  return (
    <div className="mx-auto max-w-lg">
      <Link
        href="/properties"
        className="inline-flex items-center gap-1 text-xs font-semibold text-slate"
      >
        ← Inventory
      </Link>
      <h1 className="font-display mt-2 text-2xl leading-tight text-ink">Add a listing</h1>
      <p className="mt-1 text-sm text-slate">
        Added under your name, visible to the whole firm.
      </p>
      <div className="mt-5">
        <NewPropertyForm />
      </div>
    </div>
  );
}
