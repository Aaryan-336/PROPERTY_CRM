import { NextResponse } from "next/server";

import { API_BASE, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

/**
 * How long to wait for the API before giving up.
 *
 * Generous on purpose. On Render's free plan the API is suspended after ~15
 * minutes idle, and the request that wakes it can take the better part of a
 * minute — the first sign-in of the morning routinely does. Failing at the
 * usual few seconds would report "server unreachable" for a server that is
 * merely asleep, and the operator would go looking for a fault that is not
 * there.
 */
const TIMEOUT_MS = 75_000;

export async function POST(request: Request) {
  const body = await request.json();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "user-agent": request.headers.get("user-agent") ?? "",
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    // Previously this rejected and Next returned an opaque 500, which the form
    // rendered as "Sign in failed" — indistinguishable from a wrong password,
    // and the one thing the operator most needs told apart.
    const timedOut = err instanceof Error && err.name === "TimeoutError";
    return NextResponse.json(
      {
        error: {
          code: timedOut ? "api_timeout" : "api_unreachable",
          message: timedOut
            ? "The server did not respond in time. On the free hosting plan it " +
              "sleeps when idle and can take a minute to wake — try once more."
            : "Could not reach the server. It may be starting up, or API_URL " +
              "may be pointing somewhere wrong.",
        },
      },
      { status: 503 },
    );
  }

  // A waking or overloaded host answers with an HTML error page, not JSON.
  // Parsing that blind threw, and the throw became a 500 that said nothing.
  const raw = await res.text();
  let data: {
    access_token?: string;
    expires_at?: string;
    user?: unknown;
    error?: { code: string; message: string };
  };
  try {
    data = JSON.parse(raw);
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "api_bad_response",
          message:
            res.status >= 500
              ? "The server is starting up or unhealthy. Wait a moment and try again."
              : `The server returned an unexpected response (${res.status}).`,
        },
      },
      { status: 502 },
    );
  }

  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }

  if (!data.access_token || !data.expires_at) {
    return NextResponse.json(
      {
        error: {
          code: "api_bad_response",
          message: "The server did not return a session. Try again.",
        },
      },
      { status: 502 },
    );
  }

  // The token is handed to the cookie jar here and never returned to the page,
  // so it stays out of reach of client-side JavaScript.
  const expiresAt = new Date(data.expires_at).getTime();
  const maxAge = Math.max(60, Math.floor((expiresAt - Date.now()) / 1000));

  const response = NextResponse.json({ user: data.user });
  response.cookies.set(SESSION_COOKIE, data.access_token, sessionCookieOptions(maxAge));
  return response;
}
