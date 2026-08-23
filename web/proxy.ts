import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { API_BASE, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

/**
 * Next.js 16 renamed the `middleware` convention to `proxy`.
 *
 * This is a convenience redirect only — it keeps signed-out users from landing
 * on an empty shell. It is deliberately *not* an access control: the cookie's
 * presence is never treated as proof of anything. Every page and API call
 * re-validates the token against the backend, which then scopes the query to
 * the caller's role. Treating a proxy check as the security boundary is how
 * these apps end up leaking data to anyone who can set a cookie.
 *
 * It is also where a session gets renewed, because it is the only place that
 * sees every request *and* can write a cookie — a Server Component can do
 * neither.
 */
export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const cookie = request.cookies.get(SESSION_COOKIE)?.value;

  if (!cookie && !isPublic(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }

  if (cookie && pathname === "/login") {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  const response = NextResponse.next();
  if (cookie && !isPublic(pathname)) {
    await maybeRenew(cookie, response, request.headers.get("user-agent"));
  }
  return response;
}

/**
 * Slide the session forward once it is past halfway through its life.
 *
 * The token is read here but never trusted here — the backend verifies the
 * signature, and this only decides whether it is worth asking. A forged `exp`
 * buys an attacker nothing but a refused request.
 *
 * Halfway rather than "nearly expired" so that renewal has a whole half-life
 * of chances to succeed. On the free plan the API is often asleep, and a
 * renewal that only ever fired in the last hour would be one failed wake-up
 * away from signing someone out.
 *
 * Every failure here is silent and changes nothing. This function may extend a
 * session; it must never end one. If the token really is dead the layout's own
 * check will say so, and that is the single place allowed to reach that
 * conclusion.
 */
async function maybeRenew(
  token: string,
  response: NextResponse,
  userAgent: string | null,
): Promise<void> {
  const claims = readClaims(token);
  if (!claims) return;

  const now = Date.now() / 1000;
  const halfway = claims.iat + (claims.exp - claims.iat) / 2;
  if (now < halfway) return;

  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        // The renewed session row records which device it belongs to, and
        // this is the last place that still knows.
        "user-agent": userAgent ?? "",
      },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return;

    const data = (await res.json()) as { access_token?: string; expires_at?: string };
    if (!data.access_token || !data.expires_at) return;

    const maxAge = Math.max(
      60,
      Math.floor((new Date(data.expires_at).getTime() - Date.now()) / 1000),
    );
    response.cookies.set(
      SESSION_COOKIE,
      data.access_token,
      sessionCookieOptions(maxAge),
    );
  } catch {
    // Asleep, restarting, slow. Try again on the next request — there are
    // still weeks of them before this token actually expires.
  }
}

/** The unverified payload of a JWT, for scheduling decisions only. */
function readClaims(token: string): { iat: number; exp: number } | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const json = JSON.parse(
      Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(),
    ) as { iat?: unknown; exp?: unknown };
    if (typeof json.iat !== "number" || typeof json.exp !== "number") return null;
    if (json.exp <= json.iat) return null;
    return { iat: json.iat, exp: json.exp };
  } catch {
    return null;
  }
}

function isPublic(pathname: string) {
  return (
    pathname === "/login" ||
    pathname === "/offline" ||
    pathname.startsWith("/api/auth") ||
    pathname.startsWith("/icons") ||
    pathname === "/sw.js" ||
    pathname === "/manifest.webmanifest"
  );
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
