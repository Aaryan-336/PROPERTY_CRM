import { NextResponse } from "next/server";

import { API_BASE, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

export async function POST(request: Request) {
  const body = await request.json();

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "user-agent": request.headers.get("user-agent") ?? "",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }

  // The token is handed to the cookie jar here and never returned to the page,
  // so it stays out of reach of client-side JavaScript.
  const expiresAt = new Date(data.expires_at).getTime();
  const maxAge = Math.max(60, Math.floor((expiresAt - Date.now()) / 1000));

  const response = NextResponse.json({ user: data.user });
  response.cookies.set(SESSION_COOKIE, data.access_token, sessionCookieOptions(maxAge));
  return response;
}
