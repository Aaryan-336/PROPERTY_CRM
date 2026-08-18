"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

import { Card, SectionHeading, StatusPill } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import type { WhatsAppSession } from "@/lib/types";

/**
 * Pair the WhatsApp account from the browser, in one tap.
 *
 * The QR is not something this app can produce. Only the gateway's WhatsApp
 * socket emits one, and only while it is actively asking to be linked — so a
 * gateway that already holds a saved session emits nothing at all. That was the
 * hole: this screen would sit empty with no code and nothing to press, and the
 * only way to get one was to delete the session directory on the server by
 * hand.
 *
 * So Connect is a command, not a render. It posts to /whatsapp/pair, the gateway
 * picks that up within a few seconds, clears its session and starts pairing, and
 * the QR arrives here through the same polling that was already here.
 *
 * Polling rather than streaming because the whole exchange lasts under a minute
 * and only while this screen is open. A websocket would be more elegant and more
 * to go wrong on a free-tier host that sleeps.
 */
export function ConnectWhatsApp({ initial }: { initial: WhatsAppSession }) {
  const router = useRouter();
  const [session, setSession] = useState(initial);
  const [qrImage, setQrImage] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/crm/whatsapp/session").catch(() => null);
    if (res?.ok) setSession(await res.json());
  }, []);

  const connected = session.state === "connected" && !session.stale;
  // Anything the owner is actively waiting on. A pressed Connect counts even
  // before the gateway has answered, otherwise the screen goes quiet for four
  // seconds after the one tap that matters most.
  const awaiting =
    session.pair_pending || session.state === "qr" || session.state === "connecting";

  // Fast while something is in flight (WhatsApp rotates the code about every
  // 20s and a stale one silently fails on the phone), slow otherwise so an idle
  // tab is not hammering a sleeping API.
  useEffect(() => {
    const every = awaiting ? 2000 : 10000;
    timer.current = setInterval(refresh, every);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [awaiting, refresh]);

  // The moment a scan succeeds, everything else on this screen is wrong: it was
  // server-rendered while nothing was linked, so the group picker below is
  // holding an empty list and a stale connection state. Refresh once, on the
  // transition only — polling already keeps this card itself current.
  const wasConnected = useRef(connected);
  useEffect(() => {
    if (connected && !wasConnected.current) router.refresh();
    wasConnected.current = connected;
  }, [connected, router]);

  // Render the payload to an image client-side. The QR is a live credential —
  // scanning it links an account — so it is never written to a file or sent
  // anywhere; it exists in this tab and expires in twenty seconds.
  useEffect(() => {
    if (!session.qr) {
      setQrImage(null);
      return;
    }
    let cancelled = false;
    QRCode.toDataURL(session.qr, {
      width: 320,
      margin: 2,
      errorCorrectionLevel: "M",
      color: { dark: "#1a1714", light: "#ffffff" },
    })
      .then((url) => {
        if (!cancelled) setQrImage(url);
      })
      .catch(() => setQrImage(null));
    return () => {
      cancelled = true;
    };
  }, [session.qr]);

  async function requestPairing() {
    setAsking(true);
    setError(null);
    setConfirming(false);
    const res = await fetch("/api/crm/whatsapp/pair", { method: "POST" }).catch(
      () => null,
    );
    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(
        body?.error?.message ??
          "Could not ask the gateway to pair. Try again in a moment.",
      );
      setAsking(false);
      return;
    }
    setSession(await res.json());
    setAsking(false);
  }

  async function cancelPairing() {
    setCancelling(true);
    setError(null);
    const res = await fetch("/api/crm/whatsapp/pair", { method: "DELETE" }).catch(
      () => null,
    );
    if (!res || !res.ok) {
      setError("Could not withdraw the request. Try again in a moment.");
      setCancelling(false);
      return;
    }
    setSession(await res.json());
    setCancelling(false);
  }

  return (
    <Card className="p-5">
      <SectionHeading
        title="WhatsApp connection"
        hint="Links the account whose groups are read"
        action={
          <button
            type="button"
            onClick={() => void refresh()}
            className="text-xs font-semibold text-sandstone-deep"
          >
            Refresh
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Status session={session} />
        <span className="text-[11px] text-slate">
          Last heard from the gateway {relativeTime(session.updated_at)}
        </span>
      </div>

      {connected ? (
        <div className="rounded-tile border border-hairline bg-parchment-deep px-4 py-4">
          <p className="text-sm font-semibold text-ink">
            Linked{session.display_name ? ` as ${session.display_name}` : ""}
          </p>
          {session.jid && (
            <p className="tabular mt-1 break-all text-xs text-slate">
              {session.jid.split(":")[0].replace(/@.*/, "")}
            </p>
          )}
          <p className="mt-2 text-xs leading-relaxed text-slate">
            Reading {session.watched_groups} group
            {session.watched_groups === 1 ? "" : "s"} of{" "}
            {session.directory_count} this account is in. Choose which ones
            below.
          </p>

          {/* Relinking is destructive — it unlinks whatever is connected now —
              so it is small, low down, and asks twice. */}
          {confirming ? (
            <div className="mt-3 rounded-tile bg-signal-soft px-3.5 py-3">
              <p className="text-xs leading-relaxed text-signal">
                This unlinks the account above and shows a new code to scan.
                Messages already ingested stay; nothing new arrives until the new
                account is linked and in the groups.
              </p>
              <div className="mt-2.5 flex gap-2">
                <button
                  type="button"
                  onClick={requestPairing}
                  disabled={asking}
                  className="tap rounded-pill bg-signal px-4 text-xs font-semibold text-white disabled:opacity-60"
                >
                  {asking ? "Asking…" : "Yes, link a different phone"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="tap rounded-pill border border-hairline bg-card px-4 text-xs font-semibold text-ink"
                >
                  Keep this one
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="mt-3 text-xs font-semibold text-slate underline"
            >
              Link a different phone
            </button>
          )}
        </div>
      ) : session.qr && qrImage ? (
        <div className="flex flex-col items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- a data: URI
              generated in this tab; next/image would only add a proxy hop. */}
          <img
            src={qrImage}
            alt="WhatsApp pairing QR code"
            width={280}
            height={280}
            className="rounded-tile border border-hairline bg-white p-2"
          />
          <ol className="w-full space-y-1.5 text-xs leading-relaxed text-slate">
            <li>1. Open WhatsApp on the phone you want to read groups from.</li>
            <li>
              2. <span className="font-semibold text-ink">Settings</span> →{" "}
              <span className="font-semibold text-ink">Linked devices</span> →{" "}
              <span className="font-semibold text-ink">Link a device</span>.
            </li>
            <li>3. Point it at this code.</li>
          </ol>
          <p className="text-center text-[11px] text-slate">
            The code changes every few seconds — this screen keeps up on its own,
            so just scan whatever is showing.
          </p>
        </div>
      ) : (
        <Waiting
          session={session}
          asking={asking}
          onConnect={requestPairing}
          onCancel={cancelPairing}
          cancelling={cancelling}
        />
      )}

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-tile bg-signal-soft px-4 py-2.5 text-sm text-signal"
        >
          {error}
        </p>
      )}
    </Card>
  );
}

function Status({ session }: { session: WhatsAppSession }) {
  if (session.stale && session.state !== "disconnected") {
    return <StatusPill label="Gateway not responding" tone="signal" />;
  }
  switch (session.state) {
    case "connected":
      return <StatusPill label="Connected" tone="positive" />;
    case "qr":
      return <StatusPill label="Waiting for scan" tone="warning" />;
    case "connecting":
      return <StatusPill label="Connecting" tone="warning" />;
    case "logged_out":
      return <StatusPill label="Device unlinked" tone="signal" />;
    default:
      // "disconnected" covers two different worlds. If the gateway is
      // heartbeating, it is up and simply has no WhatsApp session -- calling
      // that "offline" sent owners hunting for a process that was already
      // running, seconds after a scan that had worked.
      return session.stale ? (
        <StatusPill label="Gateway offline" tone="neutral" />
      ) : (
        <StatusPill label="Not linked" tone="neutral" />
      );
  }
}

/**
 * What to show when there is no QR yet.
 *
 * Three genuinely different situations, and saying "not connected" for all of
 * them would send the owner to the wrong fix:
 *
 *   - the gateway is running and idle → give them the button, that is the whole
 *     point of this screen
 *   - the button has been pressed → say so, because the gateway takes a few
 *     seconds to notice and silence reads as a broken tap
 *   - the gateway is not running → no button can help; something has to be
 *     started, and only a person with server access can do it
 */
function Waiting({
  session,
  asking,
  onConnect,
  onCancel,
  cancelling,
}: {
  session: WhatsAppSession;
  asking: boolean;
  onConnect: () => void;
  onCancel: () => void;
  cancelling: boolean;
}) {
  // The gateway is heartbeating, whatever state it is in. That is the only
  // thing that makes the button meaningful: there is a process to hear it.
  const gatewayAlive = !session.stale;

  if (session.pair_pending) {
    return <Pairing session={session} onCancel={onCancel} cancelling={cancelling} />;
  }

  if (!gatewayAlive) {
    return (
      <div className="rounded-tile border border-hairline bg-parchment-deep px-4 py-4">
        <p className="text-sm font-semibold text-ink">
          The gateway is not running
        </p>
        <p className="mt-1.5 text-xs leading-relaxed text-slate">
          Nothing can be read from WhatsApp until it is started, and no code can
          appear here — it is the gateway that produces one, not this app. Start
          it on the machine that holds the session:
        </p>
        <p className="tabular mt-2 rounded-tile bg-card px-3 py-2 text-[11px] text-ink">
          cd gateway &amp;&amp; npm start
        </p>
        <p className="mt-2 text-[11px] leading-relaxed text-slate">
          You can still press Connect — it is remembered, and the gateway acts on
          it as soon as it is up.
        </p>
        <ConnectButton asking={asking} onConnect={onConnect} secondary />
        {session.last_error && (
          <p className="mt-2 text-[11px] text-signal">{session.last_error}</p>
        )}
      </div>
    );
  }

  // WhatsApp drops the socket immediately after a successful scan and expects a
  // restart with the credentials it just issued. For those few seconds the
  // session is neither linked nor idle, and the old screen said "No account
  // linked yet" with a Connect button -- telling the owner their scan had
  // failed at the moment it succeeded.
  if (session.state === "connecting") {
    return (
      <div
        className="rounded-tile border border-hairline bg-parchment-deep px-4 py-4"
        role="status"
        aria-live="polite"
      >
        <div className="flex items-start gap-3">
          <Spinner />
          <div>
            <p className="text-sm font-semibold text-ink">
              Finishing the connection…
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-slate">
              WhatsApp restarts the link right after a scan. This takes a few
              seconds and completes on its own — nothing to do.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-tile border border-hairline bg-parchment-deep px-4 py-4">
      <p className="text-sm font-semibold text-ink">
        {session.state === "logged_out"
          ? "The linked device was removed"
          : "No account linked yet"}
      </p>
      <p className="mt-1.5 text-xs leading-relaxed text-slate">
        {session.state === "logged_out"
          ? "Somebody unlinked it from the phone, or WhatsApp expired it. Press Connect and scan the new code."
          : "Press Connect and a code appears here. Scan it with the phone whose groups you want read — use the firm's dedicated number, not a personal one."}
      </p>
      <ConnectButton asking={asking} onConnect={onConnect} />
      {session.last_error && (
        <p className="mt-2 text-[11px] text-signal">{session.last_error}</p>
      )}
    </div>
  );
}

function ConnectButton({
  asking,
  onConnect,
  secondary = false,
}: {
  asking: boolean;
  onConnect: () => void;
  secondary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onConnect}
      disabled={asking}
      className={`tap mt-3 w-full rounded-pill px-5 text-[15px] font-semibold disabled:opacity-60 ${
        secondary
          ? "border border-hairline bg-card text-ink"
          : "bg-sandstone text-white"
      }`}
    >
      {asking ? "Asking…" : "Connect WhatsApp"}
    </button>
  );
}

/**
 * The wait between pressing Connect and a code appearing.
 *
 * That gap is normally two or three seconds, and it can also be forever — the
 * gateway is a process on somebody's machine, and if it is not running, or its
 * secret does not match this deployment's, nothing will ever answer. The old
 * panel said "waiting for the gateway to come back" in both cases and left the
 * owner watching a sentence that never changed, with no way out.
 *
 * So it counts, and at each stage it says something different and truer than
 * "waiting". After twenty seconds it stops being optimistic and says what is
 * actually wrong, because by then it is not a slow gateway, it is a missing one.
 */
function Pairing({
  session,
  onCancel,
  cancelling,
}: {
  session: WhatsAppSession;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const [elapsed, setElapsed] = useState(0);

  // Counted from when the request was made, not from when this mounted — the
  // owner may have navigated away and come back, and restarting at zero would
  // hide a request that has been stuck for an hour.
  useEffect(() => {
    function tick() {
      const started = session.pair_requested_at
        ? new Date(session.pair_requested_at).getTime()
        : Date.now();
      setElapsed(Math.max(0, Math.round((Date.now() - started) / 1000)));
    }
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [session.pair_requested_at]);

  const gatewayAlive = !session.stale;
  const stalled = elapsed > 20 && !gatewayAlive;

  return (
    <div
      className={`rounded-tile border px-4 py-4 ${
        stalled ? "border-signal-soft bg-signal-soft" : "border-hairline bg-parchment-deep"
      }`}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        {!stalled && <Spinner />}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink">
            {stalled
              ? "Nothing has answered"
              : gatewayAlive
                ? "The gateway has it — generating a code…"
                : "Asking for a code…"}
          </p>

          {stalled ? (
            <>
              <p className="mt-1.5 text-xs leading-relaxed text-slate">
                Your request is saved, but no gateway has picked it up in{" "}
                {formatElapsed(elapsed)}. The code is produced by the gateway,
                not by this site, so one of these is true:
              </p>
              <ul className="mt-2 space-y-1 text-xs leading-relaxed text-slate">
                <li>• it is not running — start it with <code className="tabular">npm start</code></li>
                <li>• it is pointed at a different server than this one</li>
                <li>• its secret does not match this server&rsquo;s, so its reports are refused</li>
              </ul>
              <p className="mt-2 text-[11px] leading-relaxed text-slate">
                Run <code className="tabular">./check-deployment.sh</code> in the
                gateway folder — it names which one.
              </p>
            </>
          ) : (
            <p className="mt-1.5 text-xs leading-relaxed text-slate">
              {gatewayAlive
                ? "It checks every few seconds. The code appears here by itself — stay on this screen."
                : "Saved. The moment a gateway starts, it picks this up and the code appears here."}
            </p>
          )}

          <p className="tabular mt-2 text-[11px] text-slate">
            Waiting {formatElapsed(elapsed)}
          </p>

          {/* The way out. A queued command outlives this screen, so without a
              cancel the only way to stop it was for the gateway to eventually
              start and wipe a working session to show a code nobody wanted. */}
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling}
            className="tap mt-3 rounded-pill border border-hairline bg-card px-4 text-xs font-semibold text-ink disabled:opacity-60"
          >
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function Spinner() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-sandstone-deep"
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        opacity="0.25"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
