import { DisconnectReason } from "@whiskeysockets/baileys";

/**
 * Telling a dropped connection apart from a real fault.
 *
 * Split out and tested because it guards a decision with no safe default. Too
 * broad and the process swallows a genuine bug and carries on half-working;
 * too narrow and it goes back to dying every time the wifi hiccups. The cases
 * below are transcribed from crashes this gateway actually had.
 */

/**
 * Is this the ordinary sound of a socket going away?
 *
 * Baileys does work on the socket that outlives the socket. A message arrives
 * that cannot be decrypted, it queues a retry request; the wifi drops before
 * that request is sent; the send throws `Connection Closed` from inside an
 * async queue nothing in this codebase awaits. Same shape for a timed-out node
 * send, or a stream ending mid-write.
 *
 * These are not failures. A socket closing is a thing that happens to laptops,
 * and `connection.update` is already handling it five seconds later.
 * Recognising them is what lets the process treat the ones it does not
 * recognise as genuinely alarming.
 */
export function isSocketNoise(error) {
  if (!error) return false;
  const code = error.output?.statusCode ?? error.code;

  // Checked first, and the reason this function has tests. A logout is not a
  // blip: the device was unlinked from the phone and no amount of reconnecting
  // will fix it. Swallowing one would leave the gateway spinning quietly
  // forever while the owner waits for messages that can no longer arrive --
  // the exact silent failure this whole guard exists to prevent, reintroduced
  // by the guard itself. Its message ("Stream Errored") reads like network
  // trouble, so only the status code can tell them apart.
  if (FATAL_STATUSES.has(code)) return false;

  if (
    code === DisconnectReason.connectionClosed ||
    code === DisconnectReason.connectionLost ||
    code === DisconnectReason.timedOut
  ) {
    return true;
  }
  // Errno-style network faults, which arrive as a string `code` rather than a
  // Boom status.
  if (typeof code === "string" && NETWORK_ERRNOS.has(code)) return true;

  return SOCKET_MESSAGE.test(String(error.message || ""));
}

/* Disconnects a reconnect cannot cure. Each needs a person: a fresh pairing,
 * a cleared session directory, or an account that is no longer allowed. */
const FATAL_STATUSES = new Set([
  DisconnectReason.loggedOut,
  DisconnectReason.badSession,
  DisconnectReason.multideviceMismatch,
  DisconnectReason.forbidden,
]);

const NETWORK_ERRNOS = new Set([
  "ECONNRESET",
  "EPIPE",
  "ENOTFOUND",
  "ECONNREFUSED",
  "ETIMEDOUT",
  "EHOSTUNREACH",
  "ENETUNREACH",
  "ENETDOWN",
  "EAI_AGAIN",
]);

/* Deliberately anchored on connection vocabulary. "Timed Out" appears in
 * Baileys' own group-metadata failures too, which are equally survivable. What
 * must NOT match is anything describing our own logic going wrong -- a bad
 * payload, a failed write, an assertion -- because those are the ones worth
 * hearing about. */
const SOCKET_MESSAGE =
  /\b(?:connection (?:closed|lost|terminated)|socket hang up|timed out|not open|websocket|stream errored|epipe|econnreset)\b/i;
