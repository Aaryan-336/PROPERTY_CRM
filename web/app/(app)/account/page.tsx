import { redirect } from "next/navigation";

import { InstallApp } from "@/components/InstallApp";
import { ChangePassword } from "@/components/account/ChangePassword";
import { InkCard } from "@/components/ui";
import { roleLabel } from "@/lib/format";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";

export const metadata = { title: "Your account · Balaji CRM" };

/**
 * Your own account. Available to every role — a cold caller needs to be able
 * to change their password as much as the owner does, and more often, since
 * theirs was typed in for them by somebody else when the account was made.
 */
export default async function AccountPage() {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);

  return (
    <div className="mx-auto max-w-lg space-y-5">
      <InkCard className="p-5">
        <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
          Your account
        </p>
        <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
          {user.name}
        </h1>
        <p className="mt-1 text-sm text-ink-dim">
          {roleLabel(user.role)}
          {user.email ? ` · ${user.email}` : ""}
        </p>
      </InkCard>

      <InstallApp />

      <ChangePassword />
    </div>
  );
}
