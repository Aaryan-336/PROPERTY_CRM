import { redirect } from "next/navigation";

import { ImportLeads } from "@/components/import/ImportLeads";
import { api } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import type { UserWorkload } from "@/lib/types";

export const metadata = { title: "Import leads · Balaji CRM" };

/**
 * Owner-only bulk import of a calling list.
 *
 * ROLES_PERMISSIONS.md gives "Bulk export contacts" to the Owner alone, and
 * import is its mirror image — a bulk write of other people's contact details.
 * The redirect is a courtesy; the API refuses the call for any other role.
 */
export default async function ImportPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (user.role !== "owner") redirect("/");

  const staff = await api<UserWorkload[]>("/users/workload");
  return <ImportLeads staff={staff} />;
}
