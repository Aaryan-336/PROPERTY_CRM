"use client";

import { useEffect } from "react";

/** Registers the service worker and, if VAPID keys are configured, subscribes
 *  this device to push. Both are best-effort: neither should ever block the UI. */
export function ServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    let cancelled = false;

    /**
     * Tear the worker down in development, and clear what it cached.
     *
     * Next serves dev chunks from unhashed, stable URLs, so any caching layer
     * in front of them pins the browser to a stale bundle: the document is
     * fetched fresh while its JavaScript comes from cache, which surfaces as a
     * hydration mismatch and a UI that never updates however often you reload.
     *
     * This also self-heals a browser already holding a worker registered by an
     * earlier build — without it the only fix is clearing site data by hand.
     */
    async function unregisterInDev() {
      try {
        const registrations = await navigator.serviceWorker.getRegistrations();
        await Promise.all(registrations.map((r) => r.unregister()));
        if ("caches" in window) {
          const keys = await caches.keys();
          await Promise.all(
            keys.filter((k) => k.startsWith("balaji-")).map((k) => caches.delete(k)),
          );
        }
      } catch {
        /* Best effort — never block the UI. */
      }
    }

    async function register() {
      try {
        // Keyed to the build so a deploy evicts the previous one's caches.
        const version = process.env.NEXT_PUBLIC_SW_VERSION ?? "dev";
        const registration = await navigator.serviceWorker.register(
          `/sw.js?v=${encodeURIComponent(version)}`,
        );
        if (cancelled) return;
        await subscribeToPush(registration);
      } catch {
        /* PWA features are additive; the app works without them. */
      }
    }

    if (process.env.NODE_ENV === "production") {
      void register();
    } else {
      void unregisterInDev();
    }
    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}

async function subscribeToPush(registration: ServiceWorkerRegistration) {
  if (!("PushManager" in window) || Notification.permission === "denied") return;

  const configRes = await fetch("/api/crm/push/config");
  if (!configRes.ok) return;
  const config = (await configRes.json()) as { enabled: boolean; public_key?: string };
  if (!config.enabled || !config.public_key) return;

  // Only ask once the user is signed in and using the app — a permission prompt
  // on first paint gets denied, and a denied prompt is hard to recover from.
  if (Notification.permission === "default") return;

  const existing = await registration.pushManager.getSubscription();
  const subscription =
    existing ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.public_key),
    }));

  const json = subscription.toJSON();
  await fetch("/api/crm/push/subscribe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      p256dh: json.keys?.p256dh,
      auth: json.keys?.auth,
    }),
  });
}

function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}
