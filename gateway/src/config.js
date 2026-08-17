import process from "node:process";

/**
 * Configuration, read once at startup.
 *
 * Everything the gateway needs is an environment variable, and the two that
 * have no safe default (the API base and the shared secret) are hard failures
 * rather than warnings -- a gateway that starts without a secret would read
 * the firm's groups and quietly discard everything it saw.
 */

function required(name) {
  const value = process.env[name];
  if (!value) {
    console.error(
      `[config] ${name} is not set. Copy .env.example to .env and fill it in.`,
    );
    process.exit(2);
  }
  return value;
}

export const config = {
  apiBase: (process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    "",
  ),
  ingestSecret: required("WHATSAPP_INGEST_SECRET"),

  // Where the WhatsApp session lives. This directory IS the login -- anyone
  // who copies it can read the firm's groups, so it is chmod 0700 on creation
  // and must never be committed or synced.
  authDir: process.env.WHATSAPP_AUTH_DIR || "./.wa-session",

  // Disk-backed outbox. The gateway's one job is to lose nothing, so messages
  // are journalled here the moment they arrive and only removed once the API
  // has acknowledged them.
  outboxFile: process.env.OUTBOX_FILE || "./.wa-outbox.jsonl",

  // Batching. Group traffic is bursty; flushing per message would hammer the
  // API during a burst and add nothing, since extraction is asynchronous.
  batchSize: Number(process.env.BATCH_SIZE || 25),
  flushIntervalMs: Number(process.env.FLUSH_INTERVAL_MS || 3000),

  // How often to re-read the owner's watch list from the API, so toggling a
  // group in the UI takes effect without restarting the gateway.
  groupRefreshMs: Number(process.env.GROUP_REFRESH_MS || 60000),

  // How often to check whether the owner has pressed something in the CRM
  // ("Connect WhatsApp", "Refresh group list"). Short, because it sits behind a
  // button press somebody is watching -- and cheap, because the endpoint is one
  // row and answers with two booleans.
  commandPollMs: Number(process.env.COMMAND_POLL_MS || 4000),

  // Floor between two re-pairings. Clearing the session and relinking is the
  // single most account-flagging thing this process can do, and the button that
  // triggers it is one tap on a phone. A double tap must not become two
  // relinks.
  repairCooldownMs: Number(process.env.REPAIR_COOLDOWN_MS || 60000),

  // Set by hosts that expect a process to answer HTTP (Render, Fly, Railway).
  // Unset locally, where the gateway is just a long-running script and binding
  // a port would be noise. See `startHealthServer`.
  port: process.env.PORT ? Number(process.env.PORT) : null,

  // Retry backoff for a failing API, capped so a long outage does not push the
  // retry interval out to hours.
  retryBaseMs: Number(process.env.RETRY_BASE_MS || 2000),
  retryMaxMs: Number(process.env.RETRY_MAX_MS || 120000),

  // Ignore anything older than this on first connect. Without it, pairing a
  // fresh session replays weeks of scrollback and bills a full re-extraction
  // of listings that are long gone.
  maxMessageAgeMs: Number(process.env.MAX_MESSAGE_AGE_MS || 24 * 60 * 60 * 1000),

  logLevel: process.env.LOG_LEVEL || "info",
};
