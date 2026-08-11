"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    }).catch(() => null);

    if (!res) {
      setError("Could not reach the server. Check your connection.");
      setBusy(false);
      return;
    }

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      setError(body?.error?.message ?? "Sign in failed.");
      setBusy(false);
      return;
    }

    router.replace("/");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label htmlFor="email" className="mb-1.5 block text-xs font-semibold text-slate">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="tap w-full rounded-tile border border-hairline bg-card px-4 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
        />
      </div>

      <div>
        <label
          htmlFor="password"
          className="mb-1.5 block text-xs font-semibold text-slate"
        >
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="tap w-full rounded-tile border border-hairline bg-card px-4 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
        />
      </div>

      {error && (
        <p role="alert" className="rounded-tile bg-signal-soft px-4 py-2.5 text-sm text-signal">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="tap w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white transition-opacity disabled:opacity-60"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
