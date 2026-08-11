import "server-only";

import { redirect } from "next/navigation";

import { API_BASE, getToken } from "./session";

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
  }
}

/**
 * Server-side fetch against the FastAPI backend.
 *
 * Every read in this app goes through here, which means every read carries the
 * caller's own token — the backend then scopes the query to their role. The
 * frontend never asks for "all contacts" and filters afterwards; there is no
 * code path that could.
 */
export async function api<T>(
  path: string,
  init: RequestInit & { allowError?: boolean } = {},
): Promise<T> {
  const token = await getToken();
  if (!token) redirect("/login");

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...init.headers,
      authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });

  if (res.status === 401) redirect("/login?expired=1");

  if (!res.ok) {
    let code = "error";
    let message = `Request failed (${res.status})`;
    let body: unknown;
    try {
      body = await res.json();
      const parsed = body as { error?: { code: string; message: string } };
      if (parsed.error) {
        code = parsed.error.code;
        message = parsed.error.message;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiRequestError(res.status, code, message, body);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Returns null instead of throwing on 403/404, for optional panels. */
export async function apiOptional<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path);
  } catch (err) {
    if (err instanceof ApiRequestError && [403, 404].includes(err.status)) {
      return null;
    }
    throw err;
  }
}

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const out = search.toString();
  return out ? `?${out}` : "";
}
