import { NextResponse } from "next/server";

import { API_BASE, getToken } from "@/lib/session";

/**
 * Bearer-token proxy for client components (fast-logging forms, filters).
 *
 * It attaches the caller's own session token and forwards the request; it does
 * not decide anything. Authorization and row scoping stay entirely in FastAPI,
 * so this proxy has no privileges to leak: a request through it can never
 * return more than the same request made directly with that user's token.
 */
async function forward(request: Request, path: string[]) {
  const token = await getToken();
  if (!token) {
    return NextResponse.json(
      { error: { code: "unauthenticated", message: "Please sign in again." } },
      { status: 401 },
    );
  }

  const url = new URL(request.url);
  const target = `${API_BASE}/${path.join("/")}${url.search}`;

  const headers: Record<string, string> = { authorization: `Bearer ${token}` };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const res = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    cache: "no-store",
  });

  const responseType = res.headers.get("content-type") ?? "application/json";
  if (res.status === 204) return new NextResponse(null, { status: 204 });

  return new NextResponse(await res.arrayBuffer(), {
    status: res.status,
    headers: {
      "content-type": responseType,
      ...(res.headers.get("content-disposition")
        ? { "content-disposition": res.headers.get("content-disposition")! }
        : {}),
    },
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
export async function POST(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
// PUT was missing until an endpoint needed it, and its absence showed up as a
// bare 405 with an empty body — nothing in the app said which layer refused.
export async function PUT(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
export async function PATCH(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
export async function DELETE(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
