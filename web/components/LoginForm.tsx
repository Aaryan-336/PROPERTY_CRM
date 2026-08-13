"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A sign-in that is merely slow looks identical to one that has hung. On the
  // free hosting plan the API sleeps after ~15 minutes idle and the request
  // that wakes it can take most of a minute, so after a few seconds of silence
  // say what is happening rather than leaving a spinner to be interpreted.
  const [waking, setWaking] = useState(false);
  const wakeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (wakeTimer.current) clearTimeout(wakeTimer.current);
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setWaking(false);
    wakeTimer.current = setTimeout(() => setWaking(true), 4000);

    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
      // The route it calls waits up to 75s for a sleeping API; this is the
      // client's own ceiling, a little longer, so the server's specific
      // message wins rather than being pre-empted by a generic abort.
      signal: AbortSignal.timeout(80_000),
    }).catch(() => null);

    if (wakeTimer.current) clearTimeout(wakeTimer.current);
    setWaking(false);

    if (!res) {
      setError(
        "Could not reach the server. If it has been idle it may still be " +
          "starting — wait a moment and try again.",
      );
      setBusy(false);
      return;
    }

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      setError(body?.error?.message ?? "Sign in failed.");
      setBusy(false);
      return;
    }

    // Deliberately no setBusy(false) on success: the button stays disabled
    // through the navigation that follows, which is itself slow on a cold
    // server. Re-enabling it here invites a second sign-in mid-redirect.
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

      {waking && !error && (
        <p
          role="status"
          className="rounded-tile bg-sandstone-soft px-4 py-2.5 text-sm text-sandstone-deep"
        >
          Waking the server — the first sign-in after a quiet spell can take up
          to a minute. Leave this open.
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="tap w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white transition-opacity disabled:opacity-60"
      >
        {busy ? (waking ? "Still working…" : "Signing in…") : "Sign in"}
      </button>
    </form>
  );
}
