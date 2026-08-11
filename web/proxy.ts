import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Next.js 16 renamed the `middleware` convention to `proxy`.
 *
 * This is a convenience redirect only — it keeps signed-out users from landing
 * on an empty shell. It is deliberately *not* an access control: the cookie's
 * presence is never treated as proof of anything. Every page and API call
 * re-validates the token against the backend, which then scopes the query to
 * the caller's role. Treating a proxy check as the security boundary is how
 * these apps end up leaking data to anyone who can set a cookie.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasCookie = request.cookies.has(SESSION_COOKIE);

  if (!hasCookie && !isPublic(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }

  if (hasCookie && pathname === "/login") {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
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
