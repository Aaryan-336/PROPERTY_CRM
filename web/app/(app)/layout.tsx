import { redirect } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Re-validated against the backend on every request. The proxy redirect is a
  // convenience; this is the check that counts.
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);

  return <AppShell user={user}>{children}</AppShell>;
}
