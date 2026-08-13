"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import {
  BuildingIcon,
  ChevronRight,
  FeedIcon,
  FlagIcon,
  HomeIcon,
  KeyIcon,
  LogoutIcon,
  MoreIcon,
  PeopleIcon,
  PhoneIcon,
  PulseIcon,
  RouteIcon,
  ShieldIcon,
  TeamIcon,
  UploadIcon,
} from "@/components/icons";
import { OfflineBanner } from "@/components/OfflineBanner";
import { Sheet } from "@/components/Sheet";
import { Avatar } from "@/components/ui";
import { roleLabel } from "@/lib/format";
import type { Role, User } from "@/lib/types";

type NavItem = {
  href: string;
  label: string;
  icon: (p: { className?: string }) => ReactNode;
  roles: Role[];
};

/* Every destination, in sidebar order. What reaches the mobile pill is
 * decided by MOBILE_LIMIT below; the rest goes behind "More". */
const NAV: NavItem[] = [
  { href: "/", label: "Home", icon: HomeIcon, roles: ["owner", "agent", "cold_caller"] },
  { href: "/queue", label: "Queue", icon: PhoneIcon, roles: ["cold_caller"] },
  { href: "/my-calls", label: "My calls", icon: PulseIcon, roles: ["cold_caller"] },
  { href: "/contacts", label: "Leads", icon: PeopleIcon, roles: ["owner", "agent"] },
  { href: "/properties", label: "Inventory", icon: BuildingIcon, roles: ["owner", "agent"] },
  { href: "/showings", label: "Showings", icon: RouteIcon, roles: ["owner", "agent"] },
  { href: "/feed", label: "Activity", icon: PulseIcon, roles: ["owner"] },
  { href: "/escalations", label: "Escalations", icon: FlagIcon, roles: ["owner"] },
  { href: "/inventory-feed", label: "Inventory feed", icon: FeedIcon, roles: ["owner"] },
  { href: "/import", label: "Import leads", icon: UploadIcon, roles: ["owner"] },
  { href: "/team", label: "Team", icon: TeamIcon, roles: ["owner"] },
  { href: "/audit", label: "Audit", icon: ShieldIcon, roles: ["owner"] },
  // Last, and available to everyone: it is the only screen a cold caller has
  // beyond their queue, and the only way anyone changes their own password.
  { href: "/account", label: "Your account", icon: KeyIcon, roles: ["owner", "agent", "cold_caller"] },
];

/* Which items earn a slot on the small screen, per role.
 *
 * Everything a role is allowed stays reachable on a phone; this only decides
 * what is one tap away versus one tap behind "More". The owner has ten
 * destinations and a thumb-sized pill holds five, so the split is by how often
 * a thing is needed *while away from a desk*: escalations and the lead book are
 * urgent in a car, the activity feed and the audit log are end-of-day reading.
 */
const MOBILE_LIMIT: Record<Role, string[]> = {
  owner: ["/", "/contacts", "/properties", "/escalations"],
  agent: ["/", "/contacts", "/properties", "/showings"],
  // A caller's whole job is the queue, and they have no access to the lead
  // book or the inventory — the API refuses both for this role, so putting
  // them on the pill would only produce dead links.
  cold_caller: ["/", "/queue", "/my-calls"],
  manager: ["/", "/contacts", "/properties"],
};

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ user, children }: { user: User; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const [moreOpen, setMoreOpen] = useState(false);

  const allowed = NAV.filter((item) => item.roles.includes(user.role));
  const pinned = MOBILE_LIMIT[user.role] ?? MOBILE_LIMIT.agent;
  const mobileItems = allowed.filter((item) => pinned.includes(item.href));
  // Whatever the role may see but the pill has no room for. Derived rather
  // than listed a second time, so a new NAV entry can never end up reachable
  // on a laptop and invisible on a phone.
  const overflowItems = allowed.filter((item) => !pinned.includes(item.href));

  // Close the menu when navigation actually happens, not on tap: doing it in
  // the click handler flashes the sheet away before the new page is ready.
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="min-h-dvh lg:flex">
      {/* Laptop: the mobile pill reoriented into a fixed rail — same Ink
          surface and visual language, freeing full viewport height for the
          data-dense views the owner opens at day's end. */}
      <aside className="sticky top-0 hidden h-dvh w-[232px] shrink-0 flex-col bg-ink px-3 py-5 lg:flex">
        <div className="px-3 pb-6">
          <p className="font-display text-lg leading-none text-white">Balaji</p>
          <p className="tabular mt-1 text-[10px] uppercase tracking-[0.18em] text-ink-muted">
            Brokerage CRM
          </p>
        </div>

        <nav className="flex flex-1 flex-col gap-1">
          {allowed.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-tile px-3 py-2.5 text-sm transition-colors ${
                  active
                    ? "bg-sandstone font-semibold text-white"
                    : "text-ink-dim hover:bg-ink-soft hover:text-white"
                }`}
              >
                <Icon className="h-[18px] w-[18px]" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-4 rounded-tile bg-ink-soft p-3">
          <div className="flex items-center gap-2.5">
            <Avatar name={user.name} id={user.id} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-white">{user.name}</p>
              <p className="text-[11px] text-ink-muted">{roleLabel(user.role)}</p>
            </div>
          </div>
          <button
            onClick={signOut}
            className="tap mt-3 flex w-full items-center justify-center gap-2 rounded-pill border border-ink-line px-3 text-xs font-semibold text-ink-dim transition-colors hover:border-signal hover:text-signal"
          >
            <LogoutIcon className="h-4 w-4" />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile header. Kept short so the content starts high on the screen. */}
        <header className="flex items-center justify-between px-4 pt-4 lg:hidden">
          <div>
            <p className="font-display text-base leading-none text-ink">Balaji</p>
            <p className="text-[11px] text-slate">
              {user.name.split(" ")[0]} · {roleLabel(user.role)}
            </p>
          </div>
          <button
            onClick={signOut}
            aria-label="Sign out"
            className="tap flex items-center justify-center rounded-full border border-hairline bg-card text-slate"
          >
            <LogoutIcon className="h-4 w-4" />
          </button>
        </header>

        <OfflineBanner />

        <main className="flex-1 px-4 pb-32 pt-4 lg:px-8 lg:pb-10 lg:pt-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>

      {/* Mobile: floating pill, not flush with the screen edge. */}
      <nav
        aria-label="Primary"
        className="safe-bottom fixed inset-x-0 bottom-0 z-40 flex justify-center px-4 lg:hidden"
      >
        <div className="flex items-center gap-1 rounded-pill bg-ink px-2 py-2 shadow-float">
          {mobileItems.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-label={label}
                aria-current={active ? "page" : undefined}
                className={`tap flex items-center justify-center rounded-pill px-4 transition-colors ${
                  active ? "bg-sandstone text-white" : "text-ink-dim"
                }`}
              >
                <Icon className="h-[22px] w-[22px]" />
              </Link>
            );
          })}

          {overflowItems.length > 0 && (
            <button
              type="button"
              onClick={() => setMoreOpen(true)}
              aria-label="More"
              aria-expanded={moreOpen}
              className={`tap flex items-center justify-center rounded-pill px-4 transition-colors ${
                overflowItems.some((item) => isActive(pathname, item.href))
                  ? "bg-sandstone text-white"
                  : "text-ink-dim"
              }`}
            >
              <MoreIcon className="h-[22px] w-[22px]" />
            </button>
          )}
        </div>
      </nav>

      {/* Everything that did not fit the pill. A sheet rather than a second row
          of icons: these are labelled destinations reached deliberately, not
          the four things a thumb hits without looking. */}
      <Sheet
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        title="More"
        subtitle={`${user.name.split(" ")[0]} · ${roleLabel(user.role)}`}
      >
        <ul className="space-y-2">
          {overflowItems.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`tap flex items-center gap-3 rounded-tile border px-4 text-sm font-semibold transition-colors ${
                    active
                      ? "border-ink bg-ink text-white"
                      : "border-hairline bg-card text-ink"
                  }`}
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate text-left">{label}</span>
                  <ChevronRight className="h-4 w-4 shrink-0 opacity-50" />
                </Link>
              </li>
            );
          })}
        </ul>
      </Sheet>
    </div>
  );
}
