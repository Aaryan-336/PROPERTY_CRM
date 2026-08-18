/**
 * Balaji CRM — WhatsApp ingestion gateway.
 *
 * ARCHITECTURE.md §5: a separate service that maintains the WhatsApp
 * connection and forwards new messages from configured groups to an internal
 * FastAPI webhook. It is separate from the API on purpose -- it has a
 * different failure mode (session drops, rate limits, pairing expiry) and it
 * is the one component built on an unofficial integration, so isolating it
 * bounds the blast radius of both.
 *
 * A note on "using the WhatsApp API", because it shapes everything here:
 * WhatsApp's official Cloud API only delivers messages sent *to* a registered
 * business number. It cannot read group traffic at all -- there is no official
 * API, paid or otherwise, that does. Reading groups means driving a real
 * WhatsApp account over the WhatsApp Web multi-device protocol, which is what
 * Baileys implements and what TECH_STACK.md already specifies. Consequences
 * the firm should know about:
 *
 *   - it is an unofficial integration, and WhatsApp's terms permit banning
 *     accounts that automate; use a dedicated number, never a personal one
 *   - the paired account must actually be a member of every group it reads
 *   - the session can drop and need re-pairing by QR
 *
 * Everything downstream is built to survive those: messages are journalled to
 * disk before anything else, and the API deduplicates on message id, so a
 * reconnect replays rather than loses or doubles.
 *
 * Usage:
 *   npm start             # run the gateway; pairing happens from the CRM
 *   npm run pair          # optional: pair from this terminal instead
 *   npm run groups        # optional: print group ids to the terminal
 *
 * `npm start` is the only one an owner needs. Once this process is running,
 * "Connect WhatsApp" in the CRM asks it for a QR and the group list arrives on
 * its own -- the two terminal commands above are for whoever deploys it, and
 * kept only because a broken deployment is easier to diagnose from a shell.
 */

import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import process from "node:process";

// Baileys ships these as named top-level exports (its `default` is
// makeWASocket itself). Destructuring off the default export works on some
// versions and silently yields `undefined` on others, so import them by name.
import {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeWASocket,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import pino from "pino";
import qrcode from "qrcode-terminal";

import { config } from "./config.js";
import {
  appendToOutbox,
  fetchCommands,
  fetchWatchedGroups,
  pushDirectory,
  readOutbox,
  reportSession,
  rewriteOutbox,
  sendBatch,
} from "./ingest.js";

const log = pino({
  level: config.logLevel,
  transport: { target: "pino-pretty", options: { colorize: true } },
});

const args = new Set(process.argv.slice(2));
const LIST_GROUPS = args.has("--list-groups");
const PAIR_ONLY = args.has("--pair");
// Optional name filter for --list-groups. A working account is in hundreds of
// groups and only a handful carry inventory; without this the owner is asked
// to eye-scan the lot to find them.
const GROUP_FILTER = process.argv
  .slice(2)
  .filter((a) => !a.startsWith("--"))
  .join(" ")
  .trim()
  .toLowerCase();

/** group_jid -> name, refreshed from the API so the CRM stays authoritative. */
let watched = new Map();
// Mirrors the socket state for the heartbeat, which fires on a timer and so
// cannot read it from the event that last changed it.
let connected = false;
let currentJid = null;
let currentState = "connecting";
let flushing = false;
let retryDelay = config.retryBaseMs;
let shuttingDown = false;

let socket = null;
// Every socket gets a number, and its event handlers ignore anything that
// arrives after a newer socket has replaced it. Without this, closing a socket
// to re-pair fires a `close` that schedules a reconnect of the *old* creds,
// and two sockets end up racing on one account -- which looks exactly like the
// abuse WhatsApp bans for.
let generation = 0;
let repairing = false;
let lastPairAt = 0;
let lastDirectorySync = 0;

// ---------------------------------------------------------------------------
// Watch list
// ---------------------------------------------------------------------------

async function refreshWatchedGroups() {
  try {
    const groups = await fetchWatchedGroups();
    watched = new Map(groups.map((g) => [g.group_jid, g.name]));
    log.info(`watching ${watched.size} group(s)`);
  } catch (error) {
    // Keep the previous list rather than going deaf. A CRM restart must not
    // cost the firm the messages posted while it was down.
    log.warn(`could not refresh watch list (${error.message}); keeping previous`);
  }
}

// ---------------------------------------------------------------------------
// Delivery
// ---------------------------------------------------------------------------

async function flushOutbox() {
  if (flushing || shuttingDown) return;
  flushing = true;
  try {
    const pending = await readOutbox();
    if (pending.length === 0) return;

    let delivered = 0;
    while (delivered < pending.length) {
      const batch = pending.slice(delivered, delivered + config.batchSize);
      const result = await sendBatch(batch);
      delivered += batch.length;

      if (result.unknown_groups?.length) {
        // Expected right after the owner removes a group: messages already
        // journalled are dropped by the API rather than stored.
        log.debug(`API ignored ${result.unknown_groups.length} unwatched group(s)`);
      }
      log.info(
        `delivered ${batch.length} (accepted=${result.accepted} dup=${result.duplicates})`,
      );
    }

    // Only drop what was actually delivered. Anything journalled during the
    // flush stays queued for the next pass.
    const current = await readOutbox();
    rewriteOutbox(current.slice(delivered));
    retryDelay = config.retryBaseMs;
  } catch (error) {
    log.warn(`delivery failed (${error.message}); retrying in ${retryDelay}ms`);
    setTimeout(flushOutbox, retryDelay);
    retryDelay = Math.min(retryDelay * 2, config.retryMaxMs);
  } finally {
    flushing = false;
  }
}

// ---------------------------------------------------------------------------
// Message extraction from the Baileys envelope
// ---------------------------------------------------------------------------

/**
 * Pull readable text out of a WhatsApp message.
 *
 * Listings arrive as plain text, as an image caption (a photo of the flat with
 * the details underneath), or as "extended" text when the poster replied to
 * something. Media without a caption has nothing to read and is skipped -- the
 * pipeline extracts from text, not from images.
 */
function textOf(message) {
  const content = message.message;
  if (!content) return null;
  return (
    content.conversation ||
    content.extendedTextMessage?.text ||
    content.imageMessage?.caption ||
    content.videoMessage?.caption ||
    content.documentMessage?.caption ||
    null
  );
}

function handleMessage(message) {
  const remoteJid = message.key?.remoteJid;
  if (!remoteJid || !remoteJid.endsWith("@g.us")) return; // groups only
  if (!watched.has(remoteJid)) return;
  if (message.key.fromMe) return; // our own posts are not sourced inventory

  const body = textOf(message);
  if (!body || !body.trim()) return;

  const timestamp = Number(message.messageTimestamp) * 1000;
  if (timestamp && Date.now() - timestamp > config.maxMessageAgeMs) {
    // Scrollback replayed on a fresh pairing. Re-extracting weeks of dead
    // listings costs money and fills inventory with flats that are long gone.
    return;
  }

  appendToOutbox({
    wa_message_id: message.key.id,
    group_jid: remoteJid,
    body: body.trim(),
    sender_jid: message.key.participant || undefined,
    sender_name: message.pushName || undefined,
    sent_at: timestamp ? new Date(timestamp).toISOString() : undefined,
  });
}

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------

async function connect() {
  // Claim a generation before anything async: two overlapping calls to connect
  // must not both believe they own the live socket.
  const mine = ++generation;

  fs.mkdirSync(config.authDir, { recursive: true, mode: 0o700 });
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    // Baileys' own logging is extremely verbose and would bury ours.
    logger: pino({ level: "silent" }),
    // This gateway only ever reads. Marking online would show the account as
    // active and start delivering read receipts, which is both misleading to
    // the groups and more account activity than the job needs.
    markOnlineOnConnect: false,
    syncFullHistory: false,
    // Present as an ordinary desktop WhatsApp Web session. Baileys' default
    // descriptor announces the library by name in the linked-devices list on
    // the phone and in whatever WhatsApp records server-side; there is no
    // reason to be the one device on the account that looks automated.
    browser: Browsers.macOS("Desktop"),
    // Belt and braces with syncFullHistory. A fresh pairing otherwise pulls
    // months of scrollback across hundreds of groups in a burst — the single
    // most abnormal-looking thing a new device can do, and useless here since
    // MAX_MESSAGE_AGE_MS discards it anyway.
    shouldSyncHistoryMessage: () => false,
  });

  socket = sock;
  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    // A superseded socket still emits. Acting on it would report a dead
    // connection's state over a live one's, or reconnect creds we just wiped.
    if (mine !== generation) return;

    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      // Still printed for whoever is watching a terminal, but the CRM is now
      // the expected place to scan from. WhatsApp rotates the code roughly
      // every 20s and emits a fresh one, so each report supersedes the last.
      console.log(
        "\nScan this with the dedicated WhatsApp account " +
          "(Settings -> Linked devices -> Link a device), " +
          "or open Inventory feed in the CRM:\n",
      );
      qrcode.generate(qr, { small: true });
      currentState = "qr";
      void reportSession({ state: "qr", qr, qr_ttl_seconds: 20 });
    }

    if (connection === "open") {
      log.info("connected to WhatsApp");
      connected = true;
      currentState = "connected";
      currentJid = sock.user?.id ?? null;
      void reportSession({
        state: "connected",
        jid: currentJid,
        display_name: sock.user?.name ?? null,
      });
      if (PAIR_ONLY) {
        log.info("pairing complete; session saved. Re-run with `npm start`.");
        setTimeout(() => process.exit(0), 1500);
        return;
      }
      if (LIST_GROUPS) {
        await printGroups(sock);
        setTimeout(() => process.exit(0), 500);
        return;
      }
      await refreshWatchedGroups();
      // The owner's group picker is populated from this. Doing it on every
      // connect is what makes a freshly paired account immediately pickable
      // instead of empty until somebody remembers to refresh.
      await syncDirectory({ force: true });
      await flushOutbox();
    }

    if (connection === "connecting") {
      currentState = "connecting";
      void reportSession({ state: "connecting" });
    }

    if (connection === "close") {
      const status = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = status === DisconnectReason.loggedOut;
      // 515 is what WhatsApp sends immediately after a successful scan: the
      // pairing is done, and it wants the socket restarted with the credentials
      // it just issued. It is the last step of pairing, not a failure -- and
      // reporting it as one put "Stream Errored" and a Connect button in front
      // of an owner whose scan had just worked.
      const restartRequired = status === DisconnectReason.restartRequired;
      connected = false;
      currentState = loggedOut
        ? "logged_out"
        : restartRequired
          ? "connecting"
          : "disconnected";
      void reportSession({
        state: currentState,
        // Nothing went wrong on a restart, so nothing is shown. Passing the
        // library's "Stream Errored (restart required)" through would be
        // technically true and read as a broken pairing.
        last_error: restartRequired
          ? null
          : (lastDisconnect?.error?.message ?? null),
      });

      if (restartRequired && !shuttingDown) {
        // Straight away. Baileys expects the restart to be immediate, and every
        // second of delay is a second the owner spends looking at a screen that
        // does not yet say "linked" after a scan that worked.
        log.info("pairing accepted; restarting the socket");
        if (mine === generation) void connect();
        return;
      }

      if (loggedOut) {
        // The device was removed from the phone. Reconnecting with revoked
        // creds only ever fails, so the socket is dropped -- but the process
        // stays up, because it is the only thing that can produce a new QR and
        // the owner is about to ask it for one from the CRM. Exiting here used
        // to mean somebody had to SSH in and restart it first.
        socket = null;
        log.error(
          "logged out — the linked device was removed. " +
            "Press Connect WhatsApp in the CRM (Inventory feed) to re-pair.",
        );
        return;
      }
      if (shuttingDown) return;
      log.warn(`connection closed (${status}); reconnecting in 5s`);
      setTimeout(() => {
        // Same guard: a reconnect scheduled before a re-pair must not fire
        // after it and resurrect the session we deliberately cleared.
        if (mine === generation) void connect();
      }, 5000);
    }
  });

  sock.ev.on("messages.upsert", ({ messages, type }) => {
    if (mine !== generation) return;
    // 'notify' is live traffic; 'append' is history sync, which we skip so a
    // reconnect does not re-ingest the backlog.
    if (type !== "notify") return;
    for (const message of messages) {
      try {
        handleMessage(message);
      } catch (error) {
        log.warn(`could not handle message: ${error.message}`);
      }
    }
  });

  return sock;
}

/**
 * Read the account's group list off WhatsApp and hand it to the CRM.
 *
 * One call to WhatsApp, and it is the whole reason the owner no longer has to
 * transcribe `120363…@g.us` ids out of a terminal. Rate-limited because the
 * "Refresh group list" button is one tap: an impatient owner tapping it six
 * times must not become six metadata sweeps on the account.
 */
async function syncDirectory({ force = false } = {}) {
  if (!socket || !connected) return;
  if (!force && Date.now() - lastDirectorySync < 20_000) return;
  lastDirectorySync = Date.now();

  try {
    const rows = groupRows(await socket.groupFetchAllParticipating()).map((r) => ({
      group_jid: r.id,
      // Empty, not a placeholder: the API keeps the last real name it saw
      // rather than overwriting it with "(name not synced yet)".
      name: r.synced ? r.name : "",
      participants: r.participants,
    }));
    const result = await pushDirectory(rows);
    if (result.failed) {
      log.warn(`could not upload group list (${result.failed})`);
      return;
    }
    log.info(`uploaded ${rows.length} group(s) to the CRM picker`);
  } catch (error) {
    log.warn(`could not read the group list (${error.message})`);
  }
}

/**
 * Clear the saved session and start a fresh pairing, on the owner's say-so.
 *
 * The destructive half of the Connect button: whatever account is linked stops
 * being linked. Two guards, both about not getting the number flagged --
 * `repairing` stops overlapping attempts, and the cooldown stops a double tap
 * (or a command replayed after a crash) from relinking twice in a row.
 */
async function startFreshPairing() {
  if (repairing) {
    log.debug("re-pair already in progress; ignoring");
    return;
  }
  const since = Date.now() - lastPairAt;
  if (lastPairAt && since < config.repairCooldownMs) {
    log.warn(
      `re-pair asked for ${Math.round(since / 1000)}s after the last one; ` +
        `ignoring until ${Math.round(config.repairCooldownMs / 1000)}s have passed`,
    );
    return;
  }

  repairing = true;
  lastPairAt = Date.now();
  try {
    log.warn("re-pair requested from the CRM; clearing the saved session");
    connected = false;
    currentState = "connecting";
    void reportSession({ state: "connecting", last_error: null });

    // Bump the generation first so the old socket's `close` is ignored: it is
    // about to fire, and it would otherwise schedule a reconnect on creds that
    // no longer exist on disk.
    generation += 1;
    try {
      socket?.end(undefined);
    } catch {
      // Already closed, or never opened. Either way there is nothing to close.
    }
    socket = null;

    fs.rmSync(config.authDir, { recursive: true, force: true });
    await connect();
  } catch (error) {
    log.error(`re-pair failed: ${error.message}`);
    currentState = "disconnected";
    void reportSession({ state: "disconnected", last_error: error.message });
  } finally {
    repairing = false;
  }
}

/** Anything the owner has queued from the CRM since the last poll. */
async function pollCommands() {
  if (shuttingDown) return;
  const { pair, syncGroups } = await fetchCommands();
  if (pair) {
    await startFreshPairing();
    return; // connecting re-syncs the directory anyway
  }
  if (syncGroups) await syncDirectory({ force: true });
}

/**
 * Normalise Baileys' group map into rows.
 *
 * Keyed by id rather than read off the value: a group's metadata can arrive
 * before its subject has synced, and one nameless group used to take the whole
 * listing down on sort — hiding every other id the owner came for.
 */
function groupRows(groups) {
  return Object.entries(groups).map(([id, g]) => ({
    id: g?.id || id,
    name: g?.subject?.trim() || "(name not synced yet)",
    synced: Boolean(g?.subject?.trim()),
    participants: g?.participants?.length ?? 0,
  }));
}

async function printGroups(sock) {
  const rows = groupRows(await sock.groupFetchAllParticipating());
  // Unnamed groups last: they are metadata that has not synced yet, and
  // burying them keeps the part the owner can actually recognise at the top.
  rows.sort((a, b) => {
    if (a.synced !== b.synced) return a.synced ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  const shown = GROUP_FILTER
    ? rows.filter((r) => r.name.toLowerCase().includes(GROUP_FILTER))
    : rows;

  if (GROUP_FILTER) {
    console.log(
      `\n${shown.length} of ${rows.length} group(s) match "${GROUP_FILTER}":\n`,
    );
  } else {
    console.log(
      `\nThis account is in ${rows.length} group(s). ` +
        "You do not need to read these: the same list is in the CRM under " +
        "Inventory feed, with names to tick.\n" +
        "Narrow it with a search word, e.g. `npm run groups -- property`:\n",
    );
  }

  for (const row of shown) {
    console.log(`  ${row.id}\n      ${row.name}  (${row.participants} members)\n`);
  }

  if (GROUP_FILTER && shown.length === 0) {
    console.log("  Nothing matched. Run without a search word to see them all.\n");
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

/**
 * A port to answer on, for hosts that require one.
 *
 * Render, Fly and Railway all decide a process is dead if it never binds
 * `$PORT`, and this gateway has to stay up for the CRM's Connect button to
 * reach it. Deliberately says almost nothing: it is unauthenticated, so it must
 * never expose the QR or the group list. Those are Owner-only, behind the API.
 */
function startHealthServer() {
  if (!config.port) return;
  http
    .createServer((request, response) => {
      const ok = request.url === "/" || request.url === "/health";
      response.writeHead(ok ? 200 : 404, { "content-type": "application/json" });
      response.end(
        JSON.stringify(
          ok
            ? {
                state: currentState,
                watching: watched.size,
                uptime_seconds: Math.round(process.uptime()),
              }
            : { error: "not_found" },
        ),
      );
    })
    .listen(config.port, () => log.info(`health server on :${config.port}`));
}

async function main() {
  log.info(`gateway starting; API ${config.apiBase}`);

  if (!PAIR_ONLY && !LIST_GROUPS) {
    startHealthServer();

    await refreshWatchedGroups();
    setInterval(refreshWatchedGroups, config.groupRefreshMs);
    setInterval(flushOutbox, config.flushIntervalMs);

    // The owner's side of the pairing flow. Polled rather than pushed because
    // this process has no public address -- it can sit on a laptop behind NAT
    // and still be driven from a phone.
    setInterval(() => void pollCommands(), config.commandPollMs);

    // Heartbeat, so the CRM can tell "connected" from "was connected when this
    // process died". Socket events alone cannot: a killed gateway sends no
    // "close", and the last thing the API heard would be "connected" forever.
    // Comfortably inside the API's 90s staleness window.
    //
    // Every state except `qr`, which is deliberate: a report of state "qr"
    // carries no code, and the API treats that as "the QR is gone" -- so
    // heartbeating one would blank the code the owner is mid-scan of. While a
    // QR is up, WhatsApp's own 20s rotation is the heartbeat.
    setInterval(() => {
      if (currentState === "qr") return;
      void reportSession({
        state: currentState,
        jid: connected ? currentJid : null,
      });
    }, 30_000);
  }

  // A saved session connects straight through; without one this reports `qr`
  // and waits, which is what the CRM's pairing screen renders.
  if (PAIR_ONLY || LIST_GROUPS) {
    await connect();
    return;
  }

  // Long-running mode keeps trying. A first connect that throws -- no network
  // yet on a booting machine, or WhatsApp refusing the version handshake -- used
  // to end the process, and a dead process is one the owner cannot reach from
  // the CRM at all. Socket-level drops are handled by `close` above; this is
  // only about never getting off the ground.
  for (;;) {
    try {
      await connect();
      return;
    } catch (error) {
      log.error(`could not start the WhatsApp socket: ${error.message}`);
      currentState = "disconnected";
      void reportSession({ state: "disconnected", last_error: error.message });
      await new Promise((resolve) => setTimeout(resolve, 15_000));
      if (shuttingDown) return;
    }
  }
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    if (shuttingDown) process.exit(0);
    shuttingDown = true;
    log.info("shutting down; flushing outbox");
    try {
      shuttingDown = false; // allow the final flush through the guard
      await flushOutbox();
    } catch {
      // Anything still queued stays on disk and goes out on next start.
    }
    process.exit(0);
  });
}

main().catch((error) => {
  log.error(error);
  process.exit(1);
});
