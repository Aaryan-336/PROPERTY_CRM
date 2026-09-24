"use client";

import { useEffect, useState } from "react";

import { BellIcon } from "@/components/icons";
import { subscribeToPush } from "@/components/ServiceWorker";
import { Card, StatusPill } from "@/components/ui";

type State =
  | "checking"
  | "on"
  | "off"
  | "denied"
  | "install"
  | "server-off"
  | "unsupported";

function isIos(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function isStandalone(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  const existing = await navigator.serviceWorker.getRegistration();
  if (existing) return existing;
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((r) => setTimeout(() => r(null), 4000)),
  ]);
}

/**
 * Whether reminders can reach this device, and the one button that makes
 * them. The permission prompt is only ever shown from this tap -- asked on
 * page load, browsers (and people) refuse it.
 */
export function NotificationsCard() {
  const [state, setState] = useState<State>("checking");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function check(): Promise<State> {
      if (!("serviceWorker" in navigator)) return "unsupported";
      if (!("Notification" in window) || !("PushManager" in window)) {
        return isIos() && !isStandalone() ? "install" : "unsupported";
      }
      const config = await fetch("/api/crm/push/config")
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      if (!config?.enabled) return "server-off";
      if (Notification.permission === "denied") return "denied";
      if (Notification.permission !== "granted") return "off";
      const reg = await registration();
      const sub = reg ? await reg.pushManager.getSubscription() : null;
      if (reg && !sub) await subscribeToPush(reg).catch(() => {});
      return reg ? "on" : "off";
    }
    check()
      .then((s) => !cancelled && setState(s))
      .catch(() => !cancelled && setState("unsupported"));
    return () => {
      cancelled = true;
    };
  }, []);

  async function turnOn() {
    setBusy(true);
    setMessage(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "denied" : "off");
        return;
      }
      const reg = await registration();
      if (!reg) {
        setMessage("The app is still installing its background service. Reload and try again.");
        return;
      }
      await subscribeToPush(reg);
      setState("on");
    } catch {
      setMessage("Could not turn notifications on. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMessage(null);
    const res = await fetch("/api/crm/push/test", { method: "POST" }).catch(() => null);
    const body = res?.ok ? await res.json().catch(() => null) : null;
    setBusy(false);
    setMessage(
      body?.sent
        ? "Test sent — it should appear in a few seconds."
        : "Nothing was delivered. Turn notifications off and on again in the browser settings, then retry.",
    );
  }

  const copy: Record<State, [string, string, "positive" | "neutral" | "warning" | "signal"]> = {
    checking: ["Checking…", "", "neutral"],
    on: ["On", "Reminders arrive on this device at the time you set.", "positive"],
    off: ["Off", "Turn on notifications to be alerted when a reminder is due.", "warning"],
    denied: [
      "Blocked",
      "Notifications are blocked for this site. Allow them in your browser or phone settings, then reload.",
      "signal",
    ],
    install: [
      "Install first",
      "On iPhone, add Balaji to your Home Screen (Share → Add to Home Screen), open it from there, then turn notifications on.",
      "warning",
    ],
    "server-off": [
      "Not set up",
      "Notifications aren't configured on the server yet (VAPID keys). Reminders still show here and on your dashboard.",
      "neutral",
    ],
    unsupported: ["Unavailable", "This browser can't receive notifications.", "neutral"],
  };
  const [label, hint, tone] = copy[state];

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-sandstone-soft text-sandstone-deep">
          <BellIcon className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-ink">Notifications</p>
            <StatusPill label={label} tone={tone} />
          </div>
          {hint && <p className="mt-1 text-xs leading-relaxed text-slate">{hint}</p>}
          {(state === "off" || state === "on") && (
            <div className="mt-3">
              {state === "off" ? (
                <button
                  type="button"
                  onClick={turnOn}
                  disabled={busy}
                  className="press tap rounded-pill bg-sandstone px-4 text-sm font-semibold text-white disabled:opacity-50"
                >
                  {busy ? "Turning on…" : "Turn on notifications"}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={test}
                  disabled={busy}
                  className="press tap rounded-pill border border-hairline bg-card px-4 text-sm font-semibold text-ink disabled:opacity-50"
                >
                  {busy ? "Sending…" : "Send a test"}
                </button>
              )}
            </div>
          )}
          {message && <p className="mt-2 text-xs font-semibold text-slate">{message}</p>}
        </div>
      </div>
    </Card>
  );
}
