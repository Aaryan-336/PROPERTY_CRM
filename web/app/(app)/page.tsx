import { redirect } from "next/navigation";

import { AgentHome } from "@/components/home/AgentHome";
import { ColdCallerHome } from "@/components/home/ColdCallerHome";
import { OwnerHome } from "@/components/home/OwnerHome";
import { getCurrentUser } from "@/lib/session";

/**
 * Role-aware landing. Each role gets a different home screen tuned to its
 * workflow rather than one dashboard with bits hidden — the owner reviews the
 * firm, the agent works today's visits, the cold caller works the queue.
 */
export default async function Home() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  if (user.role === "owner") return <OwnerHome user={user} />;
  if (user.role === "cold_caller") return <ColdCallerHome user={user} />;
  return <AgentHome user={user} />;
}
