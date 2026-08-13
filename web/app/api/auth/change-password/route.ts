import { NextResponse } from "next/server";

import {
  API_BASE,
  SESSION_COOKIE,
  getToken,
  sessionCookieOptions,
} from "@/lib/session";

/**
 * Change password, and swap the session cookie for the token that comes back.
 *
 * Deliberately not routed through the generic /api/crm proxy. Changing a
 * password revokes every session the user has, including the one that made the
 * request, so the cookie the browser is holding is dead the moment the API
 * answers. The API issues a replacement in the same response; this route is
 * here to catch it and write it to the cookie jar.
 *
 * Through the generic proxy the new token would be handed to client-side
 * JavaScript and the cookie left stale — the user would appear to succeed and
 * then be bounced to the sign-in page on their next click.
 */
export async function POST(request: Request) {
  const token = await getToken();
  if (!token) {
    return NextResponse.json(
      { error: { code: "unauthenticated", message: "Please sign in again." } },
      { status: 401 },
    );
  }

  const body = await request.json();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/change-password`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(75_000),
    });
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "api_unreachable",
          message: "Could not reach the server. Your password is unchanged.",
        },
      },
      { status: 503 },
    );
  }

  const raw = await res.text();
  let data: {
    access_token?: string;
    expires_at?: string;
    sessions_revoked?: number;
    error?: { code: string; message: string };
  };
  try {
    data = JSON.parse(raw);
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "api_bad_response",
          message: "The server returned an unexpected response.",
        },
      },
      { status: 502 },
    );
  }

  if (!res.ok) return NextResponse.json(data, { status: res.status });

  if (!data.access_token || !data.expires_at) {
    // The change did happen server-side, so say so rather than implying it can
    // be retried — the old password no longer works.
    return NextResponse.json(
      {
        error: {
          code: "session_not_reissued",
          message:
            "Your password was changed, but this device could not be kept " +
            "signed in. Please sign in again with the new password.",
        },
      },
      { status: 502 },
    );
  }

  const expiresAt = new Date(data.expires_at).getTime();
  const maxAge = Math.max(60, Math.floor((expiresAt - Date.now()) / 1000));

  const response = NextResponse.json({
    sessions_revoked: data.sessions_revoked ?? 0,
  });
  response.cookies.set(SESSION_COOKIE, data.access_token, sessionCookieOptions(maxAge));
  return response;
}
