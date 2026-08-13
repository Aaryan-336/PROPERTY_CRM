import { redirect } from "next/navigation";

import { Performance } from "@/components/team/Performance";
import { api, qs } from "@/lib/api";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";
import type { TeamPerformance } from "@/lib/types";

export const metadata = { title: "Performance · Balaji CRM" };

/**
 * Owner's team performance dashboard (FEATURE_LIST P2).
 *
 * Owner-only, like every other view of one staff member's numbers by another.
 * The redirect is a courtesy; the API refuses the call for any other role.
 */
export default async function PerformancePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);
  if (user.role !== "owner") redirect("/");

  const params = await searchParams;
  const days = Number(params.days ?? 30);

  const data = await api<TeamPerformance>(
    `/team/performance${qs({ days: Number.isFinite(days) ? days : 30 })}`,
  );
  return <Performance data={data} />;
}
