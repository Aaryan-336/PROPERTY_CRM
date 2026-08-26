import crypto from "node:crypto";
import fs from "node:fs";
import readline from "node:readline";

import { config } from "./config.js";

/**
 * Delivery to the CRM's ingest webhook, plus the disk outbox behind it.
 *
 * The gateway's contract with the rest of the system is "lose nothing". It
 * cannot ask WhatsApp to redeliver a message it dropped, so every message is
 * appended to a journal on arrival and only removed once the API has taken
 * responsibility for it. A crash, an API restart or a long outage costs a
 * replay, never data.
 *
 * Replay safety is the API's side of the bargain: it keys on `wa_message_id`
 * and ignores anything it has already stored, so re-sending is free.
 */

/** HMAC-SHA256 over `<timestamp>.<raw body>`, matching verify_gateway_signature. */
export function sign(body, timestamp) {
  return crypto
    .createHmac("sha256", config.ingestSecret)
    .update(`${timestamp}.`)
    .update(body)
    .digest("hex");
}

async function post(path, bodyObject) {
  const body = Buffer.from(JSON.stringify(bodyObject));
  const timestamp = String(Math.floor(Date.now() / 1000));

  const response = await fetch(`${config.apiBase}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-balaji-signature": sign(body, timestamp),
      "x-balaji-timestamp": timestamp,
    },
    body,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`${path} -> HTTP ${response.status} ${text.slice(0, 300)}`);
  }
  return response.json();
}

export async function sendBatch(messages) {
  return post("/internal/whatsapp/ingest", { messages });
}

/**
 * Tell the API what the WhatsApp socket is doing, including the pairing QR.
 *
 * This is what lets the owner pair from the browser instead of reading ASCII
 * art out of a terminal on whatever box this runs on. It is best-effort on
 * purpose: if the API is down, the gateway must keep reading messages and
 * journalling them, and a failed status ping is not a reason to stop.
 */
export async function reportSession(report) {
  try {
    await post("/internal/whatsapp/session", report);
  } catch (error) {
    // Debug, not warn. A gateway that cannot reach the API already says so
    // loudly on every delivery attempt; repeating it per heartbeat is noise.
    return { failed: error.message };
  }
  return { ok: true };
}

/**
 * Signed GET. An empty body is still a signed body, so the same HMAC scheme
 * covers reads; the endpoints refuse unsigned callers either way.
 */
async function get(path) {
  const timestamp = String(Math.floor(Date.now() / 1000));
  const response = await fetch(`${config.apiBase}${path}`, {
    method: "GET",
    headers: {
      "x-balaji-signature": sign(Buffer.from(""), timestamp),
      "x-balaji-timestamp": timestamp,
    },
  });
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return response.json();
}

/**
 * Fetch the owner's watch list.
 *
 * The API is the single source of truth for which groups are monitored -- the
 * owner toggles a group in the CRM and the gateway picks it up on the next
 * refresh. Configuring the list in two places would guarantee they drift.
 */
export async function fetchWatchedGroups() {
  const data = await get("/internal/whatsapp/groups");
  return data.groups || [];
}

/**
 * Poll for work the owner has queued from the browser.
 *
 * The gateway is the only process that can produce a pairing QR, and it only
 * produces one while it is asking WhatsApp to be linked. So "show me a QR" has
 * to travel from the owner's screen to here, and this is the wire it travels
 * on. Best-effort: the API being briefly unreachable must never stop the
 * gateway reading and journalling messages.
 */
export async function fetchCommands() {
  try {
    const data = await get("/internal/whatsapp/commands");
    return {
      pair: Boolean(data.pair),
      syncGroups: Boolean(data.sync_groups),
      // Milliseconds, or null. The gateway compares this against the moment it
      // connected, to tell a request meant to revive a dead gateway from one
      // meant to link a different phone.
      pairRequestedAt: data.pair_requested_at
        ? Date.parse(data.pair_requested_at)
        : null,
    };
  } catch {
    return { pair: false, syncGroups: false, pairRequestedAt: null };
  }
}

/**
 * Upload every group the linked account is in.
 *
 * This is what removed `npm run groups` from the owner's life: they used to
 * read `120363…@g.us` ids out of a terminal and paste them in one at a time.
 * The gateway already has the list; sending it means the CRM can offer names
 * and member counts to tick.
 *
 * Names only, no message content -- this is a directory, not a read of the
 * groups. Nothing here implies a group is being ingested; that is still the
 * owner's explicit choice in the CRM.
 */
export async function pushDirectory(groups) {
  try {
    return await post("/internal/whatsapp/directory", { groups });
  } catch (error) {
    return { failed: error.message };
  }
}

/** Append-only journal. One JSON object per line, fsync'd by the OS. */
export function appendToOutbox(message) {
  fs.appendFileSync(config.outboxFile, `${JSON.stringify(message)}\n`, "utf8");
}

export async function readOutbox() {
  if (!fs.existsSync(config.outboxFile)) return [];
  const messages = [];
  const stream = readline.createInterface({
    input: fs.createReadStream(config.outboxFile, "utf8"),
    crlfDelay: Infinity,
  });
  for await (const line of stream) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      messages.push(JSON.parse(trimmed));
    } catch {
      // A torn final line from a crash mid-append. Skipping one malformed
      // record is better than refusing to start and stalling the whole feed.
    }
  }
  return messages;
}

/**
 * Rewrite the journal with only what is still undelivered.
 *
 * Rewrite-and-rename so an interrupted flush cannot truncate the outbox: the
 * old file stays intact until the replacement is complete on disk.
 */
export function rewriteOutbox(remaining) {
  const temp = `${config.outboxFile}.tmp`;
  fs.writeFileSync(
    temp,
    remaining.map((m) => JSON.stringify(m)).join("\n") + (remaining.length ? "\n" : ""),
    "utf8",
  );
  fs.renameSync(temp, config.outboxFile);
}
