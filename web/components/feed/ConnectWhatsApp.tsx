"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

import { Card, SectionHeading, StatusPill } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import type { WhatsAppSession } from "@/lib/types";

/**
 * Pair the WhatsApp account from the browser.
 *
 * Pairing used to mean running `npm run pair` on whatever box hosts the
 * gateway and scanning ASCII art out of a terminal. The person holding the
 * phone is the owner, who has no terminal — so the gateway now pushes its QR
 * to the API and this polls for it.
 *
 * Polls rather than streams because the whole exchange lasts under a minute
 * and only while this screen is open. A websocket would be more elegant and
 * more to go wrong on a free-tier host that sleeps.
 */
export function ConnectWhatsApp({ initial }: { initial: WhatsAppSession }) {
  const [session, setSession] = useState(initial);
  const [qrImage, setQrImage] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/crm/whatsapp/session").catch(() => null);
    if (res?.ok) setSession(await res.json());
  }, []);

  // Fast while a code is on screen (WhatsApp rotates it about every 20s and a
  // stale one silently fails on the phone), slow otherwise so an idle tab is
  // not hammering a sleeping API.
  useEffect(() => {
    const active = session.state === "qr" || session.state === "connecting";
    const every = active ? 2000 : 10000;
    timer.current = setInterval(refresh, every);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [session.state, refresh]);

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

  async function poke() {
    setPolling(true);
    await refresh();
    setPolling(false);
  }

  const connected = session.state === "connected" && !session.stale;

  return (
    <Card className="p-5">
      <SectionHeading
        title="WhatsApp connection"
        hint="Links the account whose groups are read"
        action={
          <button
            type="button"
            onClick={poke}
            disabled={polling}
            className="text-xs font-semibold text-sandstone-deep disabled:opacity-60"
          >
            {polling ? "Checking…" : "Refresh"}
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
          <p className="mt-2 text-xs text-slate">
            Reading {session.watched_groups} group
            {session.watched_groups === 1 ? "" : "s"}. Add or remove them below.
          </p>
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
            The code changes every few seconds — this screen keeps up on its
            own, so just scan whatever is showing.
          </p>
        </div>
      ) : (
        <Waiting session={session} />
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
      return <StatusPill label="Gateway offline" tone="neutral" />;
  }
}

/**
 * What to do when there is no QR to show.
 *
 * Each of these is a different problem with a different fix, and saying
 * "not connected" for all of them would send the owner to the wrong one.
 */
function Waiting({ session }: { session: WhatsAppSession }) {
  const stale = session.stale;

  return (
    <div className="rounded-tile border border-hairline bg-parchment-deep px-4 py-4">
      {session.state === "logged_out" ? (
        <>
          <p className="text-sm font-semibold text-ink">
            The linked device was removed
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-slate">
            Somebody unlinked it from the phone, or WhatsApp expired it. The
            gateway needs its saved session cleared and restarted, then a code
            will appear here to scan.
          </p>
        </>
      ) : stale || session.state === "disconnected" ? (
        <>
          <p className="text-sm font-semibold text-ink">
            The gateway is not running
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-slate">
            Nothing can be read from WhatsApp until it is started, and no code
            can appear here. Start it on the machine that holds the session:
          </p>
          <p className="tabular mt-2 rounded-tile bg-card px-3 py-2 text-[11px] text-ink">
            cd gateway &amp;&amp; npm start
          </p>
        </>
      ) : (
        <p className="text-sm text-slate">
          Connecting to WhatsApp — a code will appear here in a moment.
        </p>
      )}

      {session.last_error && (
        <p className="mt-2 text-[11px] text-signal">{session.last_error}</p>
      )}
    </div>
  );
}
