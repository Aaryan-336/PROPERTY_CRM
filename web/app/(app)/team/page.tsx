import { redirect } from "next/navigation";

import { TeamBoard } from "@/components/team/TeamBoard";
import { api } from "@/lib/api";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";
import type { UserWorkload } from "@/lib/types";

export const metadata = { title: "Team · Balaji CRM" };

/**
 * Owner's staff management screen.
 *
 * ROLES_PERMISSIONS.md makes "Manage users/roles" Owner-only. The redirect
 * here is a courtesy so a mistyped URL lands somewhere sensible — the actual
 * enforcement is the `users.manage` capability on the API, which refuses these
 * calls regardless of what the UI shows.
 */
export default async function TeamPage() {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);
  if (user.role !== "owner") redirect("/");

  const team = await api<UserWorkload[]>("/users/workload");

  return <TeamBoard rows={team} currentUserId={user.id} />;
}
