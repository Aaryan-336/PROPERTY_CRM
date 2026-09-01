import assert from "node:assert/strict";
import test from "node:test";

import { isSocketNoise } from "../src/resilience.js";

/** The exact shape that killed the gateway on 26 Aug at 22:50, from the log. */
function theCrashThatStartedThis() {
  const error = new Error("Connection Closed");
  error.isBoom = true;
  error.data = null;
  error.output = {
    statusCode: 428,
    payload: {
      statusCode: 428,
      error: "Precondition Required",
      message: "Connection Closed",
    },
    headers: {},
  };
  return error;
}

test("the crash that killed the gateway is recognised", () => {
  // Baileys threw this from `sendRetryRequest` after a wifi drop closed the
  // socket mid-flight. Node terminated the process over it, and the owner read
  // that as WhatsApp having logged them out.
  assert.equal(isSocketNoise(theCrashThatStartedThis()), true);
});

test("a lost connection and a timeout are recognised", () => {
  const lost = new Error("Connection Lost");
  lost.output = { statusCode: 408 };
  assert.equal(isSocketNoise(lost), true);
  assert.equal(isSocketNoise(new Error("Timed Out")), true);
});

test("errno-style network faults are recognised", () => {
  for (const code of ["ECONNRESET", "EPIPE", "ENETDOWN", "EAI_AGAIN"]) {
    const error = new Error("read error");
    error.code = code;
    assert.equal(isSocketNoise(error), true, code);
  }
});

test("a socket hang up is recognised", () => {
  assert.equal(isSocketNoise(new Error("socket hang up")), true);
});

test("a genuine bug is NOT swallowed", () => {
  // The whole risk of a crash guard: staying up through a real fault, half
  // working, with nobody told. These must reach the loud branch.
  for (const message of [
    "Cannot read properties of undefined (reading 'key')",
    "watched.has is not a function",
    "Unexpected token < in JSON at position 0",
    "ENOSPC: no space left on device, write",
    "Invalid signature on ingest response",
  ]) {
    assert.equal(isSocketNoise(new Error(message)), false, message);
  }
});

test("a logout is NOT socket noise", () => {
  // 401 means the device was unlinked from the phone. That genuinely does need
  // a human and a fresh pairing, and must never be filed under "wifi blip".
  const error = new Error("Stream Errored (unlinked)");
  error.output = { statusCode: 401 };
  assert.equal(isSocketNoise(error), false);
});

test("null and undefined are not noise", () => {
  assert.equal(isSocketNoise(null), false);
  assert.equal(isSocketNoise(undefined), false);
});
