import { redirect } from "next/navigation";

import { DatabaseCards } from "@/components/import/DatabaseCards";
import { ImportLeads } from "@/components/import/ImportLeads";
import { api } from "@/lib/api";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";
import type { BatchPerformance, UserWorkload } from "@/lib/types";

export const metadata = { title: "Import leads · Balaji CRM" };

/**
 * Owner-only bulk import of a calling list.
 *
 * ROLES_PERMISSIONS.md gives "Bulk export contacts" to the Owner alone, and
 * import is its mirror image — a bulk write of other people's contact details.
 * The redirect is a courtesy; the API refuses the call for any other role.
 *
 * The uploaded lists and their performance live on the same screen as the
 * upload form on purpose: deciding whether to buy another list is the same
 * sitting as uploading one, and splitting them across two pages would mean
 * nobody ever looks at the numbers.
 */
export default async function ImportPage() {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);
  if (user.role !== "owner") redirect("/");

  const [staff, batches] = await Promise.all([
    api<UserWorkload[]>("/users/workload"),
    api<BatchPerformance[]>("/lead-batches"),
  ]);

  return (
    <div className="space-y-6">
      <ImportLeads staff={staff} />
      <DatabaseCards batches={batches} />
    </div>
  );
}
