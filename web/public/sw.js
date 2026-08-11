/* Balaji CRM service worker.
 *
 * Two jobs, both from PHASES.md Phase 1:
 *   1. Cache recently-viewed leads and inventory so a phone in a basement can
 *      still show what it loaded upstairs.
 *   2. Receive Web Push for follow-up reminders and owner escalations.
 *
 * Deliberately read-only offline: writes are never queued and replayed. A call
 * log that silently syncs an hour later would corrupt the very timeline the
 * owner relies on, so the UI tells the user a log needs a connection instead of
 * pretending it succeeded. Offline write support is a later-phase decision.
 */

// Keyed to the build, passed in on the register URL (see ServiceWorker.tsx).
// A hardcoded constant here meant the activate handler below — which deletes
// caches that do not match the current version — could never evict anything,
// so every deploy left users on the previous build's assets.
const BUILD = new URL(self.location.href).searchParams.get("v") || "dev";
const VERSION = `balaji-${BUILD}`;
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;

const SHELL_ASSETS = ["/", "/offline", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => !key.startsWith(VERSION))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache auth: a stale session response would be both wrong and unsafe.
  if (url.pathname.startsWith("/api/auth")) return;

  // Read APIs: network first, fall back to the last good copy.
  if (url.pathname.startsWith("/api/crm")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(DATA_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() =>
          caches.match(request).then(
            (cached) =>
              cached ??
              new Response(
                JSON.stringify({
                  error: {
                    code: "offline",
                    message: "You are offline and this data has not been loaded yet.",
                  },
                }),
                { status: 503, headers: { "content-type": "application/json" } },
              ),
          ),
        ),
    );
    return;
  }

  // Pages: network first so staff see live data, cache as the safety net.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          return cached ?? caches.match("/offline");
        }),
    );
    return;
  }

  // Static assets: cache first — but only the immutable ones.
  //
  // `/_next/static/**` filenames carry a content hash in a production build, so
  // a changed file is a changed URL and cache-first is safe. Everything else
  // under `/_next/` is not hashed (dev chunks, RSC payloads, HMR), and serving
  // those cache-first pins the browser to a stale JS bundle indefinitely: the
  // document is fetched fresh while its chunks come from cache, which shows up
  // as a hydration mismatch and a UI that never updates no matter how many
  // times the page is reloaded.
  const immutable = url.pathname.startsWith("/_next/static/");
  if (!immutable) {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ??
        fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        }),
    ),
  );
});

self.addEventListener("push", (event) => {
  if (!event.data) return;
  let payload = {};
  try {
    payload = event.data.json();
  } catch {
    payload = { title: "Balaji CRM", body: event.data.text() };
  }

  event.waitUntil(
    self.registration.showNotification(payload.title || "Balaji CRM", {
      body: payload.body || "",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: payload.tag || undefined,
      data: { url: payload.url || "/" },
      vibrate: [40, 30, 40],
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          if ("focus" in client) {
            client.navigate(target);
            return client.focus();
          }
        }
        return self.clients.openWindow(target);
      }),
  );
});
