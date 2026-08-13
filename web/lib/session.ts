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

export async function getCurrentUser(): Promise<User | null> {
  const token = await getToken();
  if (!token) return null;

  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as User;
}
