import { redirect } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import { SESSION_EXPIRED_ROUTE, checkSession } from "@/lib/session";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Re-validated against the backend on every request. The proxy redirect is a
  // convenience; this is the check that counts.
  //
  // The three outcomes are kept apart deliberately. This used to collapse
  // "the API said no" and "the API said nothing" into a single null, and treat
  // both as an expired session -- so every time the free-tier API dozed off or
  // restarted, the next page load deleted a perfectly good cookie and dumped
  // the user on the sign-in screen. That is what "it logs me out every now and
  // again" actually was, and no session length would have fixed it.
  const check = await checkSession();

  if (check.status === "unauthenticated") redirect(SESSION_EXPIRED_ROUTE);
  if (check.status === "unavailable") return <ServerUnreachable />;

  return <AppShell user={check.user}>{children}</AppShell>;
}

/**
 * The API could not be reached. The session is untouched and still valid.
 *
 * No sign-in link here on purpose: signing in is not the remedy and offering
 * it teaches people to re-enter a password whenever the server hiccups, which
 * is the habit that phishing relies on. Reloading is the remedy.
 */
function ServerUnreachable() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-parchment px-6 text-center">
      <div className="max-w-sm">
        <p className="font-display text-2xl text-ink">Can&rsquo;t reach the server</p>
        <p className="mt-3 text-sm leading-relaxed text-slate">
          You are still signed in — this is the server, not your session. On the
          free hosting plan it sleeps when nobody has used it for a while and
          takes up to a minute to wake.
        </p>
        <form className="mt-6">
          <button
            type="submit"
            className="tap rounded-pill bg-ink px-6 text-sm font-semibold text-white"
          >
            Try again
          </button>
        </form>
      </div>
    </main>
  );
}
