import { redirect } from "next/navigation";

import { AgentHome } from "@/components/home/AgentHome";
import { ColdCallerHome } from "@/components/home/ColdCallerHome";
import { OwnerHome } from "@/components/home/OwnerHome";
import { VoiceQuickAdd } from "@/components/voice/VoiceQuickAdd";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";

/**
 * Role-aware landing. Each role gets a different home screen tuned to its
 * workflow rather than one dashboard with bits hidden — the owner reviews the
 * firm, the agent works today's visits, the cold caller works the queue.
 */
export default async function Home() {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);

  const home =
    user.role === "owner" ? (
      <OwnerHome user={user} />
    ) : user.role === "cold_caller" ? (
      <ColdCallerHome user={user} />
    ) : (
      <AgentHome user={user} />
    );
  return (
    <>
      {home}
      <VoiceQuickAdd role={user.role} variant="fab" />
    </>
  );
}
