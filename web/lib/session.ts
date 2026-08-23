import "server-only";

import { cookies } from "next/headers";

import type { User } from "./types";

export const SESSION_COOKIE = "balaji_session";
export const API_BASE = process.env.API_URL ?? "http://127.0.0.1:8000";

/**
 * The JWT lives in an httpOnly cookie set by this app's own route handlers and
 * is attached to backend calls as a bearer token server-side. Client JavaScript
 * never sees it, so an XSS bug cannot exfiltrate a working session — which
 * matters more than usual here, where the threat model is people who already
 * have legitimate accounts.
 */
export async function getToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

export function sessionCookieOptions(maxAgeSeconds: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: maxAgeSeconds,
  };
}

/**
 * Where to send a request whose session did not check out.
 *
 * Not "/login". Everything under (app) only renders when a cookie is present —
 * the proxy redirects when it is missing — so a null user here means the
 * cookie is stale, and sending the browser to /login leaves it in place for
 * the proxy to bounce straight back. That was an inescapable redirect loop:
 * signing in again was impossible without clearing site data by hand.
 *
 * This route clears the cookie first, which a Server Component cannot do.
 */
export const SESSION_EXPIRED_ROUTE = "/api/auth/expired";

/**
 * Why a request for the current user did not produce one.
 *
 * The distinction is the whole point. `unauthenticated` means the backend
 * looked at the token and rejected it, and the right response is to clear the
 * cookie and ask for a password. `unavailable` means nobody looked at
 * anything -- the API is asleep, restarting, or briefly 502ing behind its
 * host -- and clearing the cookie there signs out someone whose session is
 * perfectly good, which is what used to happen every time the free-tier API
 * dozed off.
 */
export type SessionCheck =
  | { status: "ok"; user: User }
  | { status: "unauthenticated" }
  | { status: "unavailable" };

/**
 * How long to wait for the API before calling it unavailable.
 *
 * The same reasoning as the login route's timeout: on the free plan a
 * suspended API can take most of a minute to answer its first request, and
 * giving up after the usual few seconds would report a fault that is not
 * there. Erring long is safe here because the alternative -- a false
 * `unavailable` -- costs a retry, while a false `unauthenticated` costs a
 * sign-in.
 */
const ME_TIMEOUT_MS = 75_000;

export async function checkSession(): Promise<SessionCheck> {
  const token = await getToken();
  if (!token) return { status: "unauthenticated" };

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/me`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(ME_TIMEOUT_MS),
    });
  } catch {
    // Refused, reset, DNS, timeout. None of these are a statement about the
    // token, so none of them may cost the user their session.
    return { status: "unavailable" };
  }

  // Only the backend saying "no" counts as a no. A 500 from the app, a 502
  // from the host's proxy and an HTML holding page all mean "ask again".
  if (res.status === 401 || res.status === 403) return { status: "unauthenticated" };
  if (!res.ok) return { status: "unavailable" };

  try {
    return { status: "ok", user: (await res.json()) as User };
  } catch {
    // A waking host answers with an HTML error page, not JSON.
    return { status: "unavailable" };
  }
}

/** Convenience for callers that genuinely only care whether someone is here. */
export async function getCurrentUser(): Promise<User | null> {
  const check = await checkSession();
  return check.status === "ok" ? check.user : null;
}
