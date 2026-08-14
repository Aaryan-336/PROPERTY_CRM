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
 * Fetch the owner's watch list.
 *
 * The API is the single source of truth for which groups are monitored -- the
 * owner toggles a group in the CRM and the gateway picks it up on the next
 * refresh. Configuring the list in two places would guarantee they drift.
 *
 * Signed like the ingest call. A GET with an empty signed body is still an
 * authenticated request; the endpoint refuses unsigned callers.
 */
export async function fetchWatchedGroups() {
  const body = Buffer.from("");
  const timestamp = String(Math.floor(Date.now() / 1000));
  const response = await fetch(`${config.apiBase}/internal/whatsapp/groups`, {
    method: "GET",
    headers: {
      "x-balaji-signature": sign(body, timestamp),
      "x-balaji-timestamp": timestamp,
    },
  });
  if (!response.ok) {
    throw new Error(`group fetch -> HTTP ${response.status}`);
  }
  const data = await response.json();
  return data.groups || [];
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
