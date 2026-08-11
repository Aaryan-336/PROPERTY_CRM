import { NextResponse } from "next/server";

import { API_BASE, SESSION_COOKIE, getToken } from "@/lib/session";

export async function POST() {
  const token = await getToken();

  // Revoke server-side first: clearing the cookie alone would leave a usable
  // token behind for anyone who captured it.
  if (token) {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
    }).catch(() => undefined);
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}
