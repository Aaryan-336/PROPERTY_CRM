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
 *   npm run pair          # first-time QR pairing
 *   npm run groups        # print group ids, to paste into the CRM
 *   npm start             # run the gateway
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

// Baileys ships these as named top-level exports (its `default` is
// makeWASocket itself). Destructuring off the default export works on some
// versions and silently yields `undefined` on others, so import them by name.
import {
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
  fetchWatchedGroups,
  readOutbox,
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

/** group_jid -> name, refreshed from the API so the CRM stays authoritative. */
let watched = new Map();
let flushing = false;
let retryDelay = config.retryBaseMs;
let shuttingDown = false;

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
  fs.mkdirSync(config.authDir, { recursive: true, mode: 0o700 });
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
  const { version } = await fetchLatestBaileysVersion();

  const socket = makeWASocket({
    version,
    auth: state,
    // Baileys' own logging is extremely verbose and would bury ours.
    logger: pino({ level: "silent" }),
    // This gateway only ever reads. Marking online would show the account as
    // active and start delivering read receipts, which is both misleading to
    // the groups and more account activity than the job needs.
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });

  socket.ev.on("creds.update", saveCreds);

  socket.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log(
        "\nScan this with the dedicated WhatsApp account " +
          "(Settings -> Linked devices -> Link a device):\n",
      );
      qrcode.generate(qr, { small: true });
    }

    if (connection === "open") {
      log.info("connected to WhatsApp");
      if (PAIR_ONLY) {
        log.info("pairing complete; session saved. Re-run with `npm start`.");
        setTimeout(() => process.exit(0), 1500);
        return;
      }
      if (LIST_GROUPS) {
        await printGroups(socket);
        setTimeout(() => process.exit(0), 500);
        return;
      }
      await refreshWatchedGroups();
      await flushOutbox();
    }

    if (connection === "close") {
      const status = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = status === DisconnectReason.loggedOut;
      if (loggedOut) {
        // The session was revoked from the phone. Reconnecting in a loop would
        // never succeed; a human has to re-pair.
        log.error(
          "logged out — the linked device was removed. " +
            `Delete ${config.authDir} and run \`npm run pair\` again.`,
        );
        process.exit(1);
      }
      if (shuttingDown) return;
      log.warn(`connection closed (${status}); reconnecting in 5s`);
      setTimeout(connect, 5000);
    }
  });

  socket.ev.on("messages.upsert", ({ messages, type }) => {
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

  return socket;
}

async function printGroups(socket) {
  const groups = await socket.groupFetchAllParticipating();
  const rows = Object.values(groups).map((g) => ({
    id: g.id,
    name: g.subject,
    participants: g.participants?.length ?? 0,
  }));
  rows.sort((a, b) => a.name.localeCompare(b.name));

  console.log(
    `\nThis account is in ${rows.length} group(s). ` +
      "Add the ones carrying inventory in the CRM (Owner -> Inventory feed):\n",
  );
  for (const row of rows) {
    console.log(`  ${row.id}\n      ${row.name}  (${row.participants} members)\n`);
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

async function main() {
  log.info(`gateway starting; API ${config.apiBase}`);

  if (!PAIR_ONLY && !LIST_GROUPS) {
    await refreshWatchedGroups();
    setInterval(refreshWatchedGroups, config.groupRefreshMs);
    setInterval(flushOutbox, config.flushIntervalMs);
  }

  await connect();
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
