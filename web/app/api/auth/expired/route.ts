import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Land here when the session cookie is present but the token behind it is not
 * accepted — expired, revoked by a password change, or signed by a JWT_SECRET
 * that has since been rotated.
 *
 * It exists because a Server Component cannot delete a cookie, and something
 * has to. Without it the stale cookie survived and produced a redirect loop:
 * `/` saw a 401 and sent the browser to `/login`, the proxy saw a cookie and
 * sent it back to `/`, forever. The user could not sign in and clearing site
 * data by hand was the only way out.
 */
export async function GET(request: Request) {
  const url = new URL("/login?expired=1", request.url);
  const response = NextResponse.redirect(url);
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
