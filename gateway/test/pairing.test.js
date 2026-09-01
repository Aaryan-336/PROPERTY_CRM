import assert from "node:assert/strict";
import test from "node:test";

import { shouldIgnorePairRequest } from "../src/pairing.js";

const NOW = Date.parse("2026-09-01T14:26:00Z");
const MIN = 60_000;

test("the exact situation on 1 Sep: stale request, session on disk, not yet connected", () => {
  // The gateway crashed six days ago. The owner pressed Connect 1h40m back at a
  // screen reading GATEWAY NOT RESPONDING, meaning "wake up". Starting the
  // gateway now must not read that as "relink" and destroy a session that has
  // been valid since 26 Aug.
  const ignored = shouldIgnorePairRequest({
    pairRequestedAt: NOW - 100 * MIN,
    connectedAt: null, // still connecting -- the hole in the old guard
    startedAt: NOW,
    hasStoredSession: true,
  });
  assert.equal(ignored, true);
});

test("a deliberate relink at a connected screen is honoured", () => {
  // Gateway up since yesterday, owner sees the linked account and asks to swap
  // phones. This is the one press that is allowed to wipe the session.
  const ignored = shouldIgnorePairRequest({
    pairRequestedAt: NOW,
    connectedAt: NOW - 24 * 60 * MIN,
    startedAt: NOW - 24 * 60 * MIN,
    hasStoredSession: true,
  });
  assert.equal(ignored, false);
});

test("first-time setup is never blocked", () => {
  // No creds on disk: there is nothing to protect, and refusing here would
  // strand the very first pairing forever.
  const ignored = shouldIgnorePairRequest({
    pairRequestedAt: NOW - 100 * MIN,
    connectedAt: null,
    startedAt: NOW,
    hasStoredSession: false,
  });
  assert.equal(ignored, false);
});

test("an undated request does not get the benefit of the doubt", () => {
  assert.equal(
    shouldIgnorePairRequest({
      pairRequestedAt: null,
      connectedAt: null,
      startedAt: NOW,
      hasStoredSession: true,
    }),
    true,
  );
});

test("a request made after this run started, while still connecting, is honoured", () => {
  // Pressed 30s into a run. Ambiguous, but they pressed it just now and with a
  // live process -- and they can always press again.
  assert.equal(
    shouldIgnorePairRequest({
      pairRequestedAt: NOW,
      connectedAt: null,
      startedAt: NOW - 30_000,
      hasStoredSession: true,
    }),
    false,
  );
});

test("connectedAt wins over startedAt once there is a connection", () => {
  // Reconnected mid-run at NOW-5m; a request from NOW-10m predates the
  // connection and is stale even though it postdates process start.
  assert.equal(
    shouldIgnorePairRequest({
      pairRequestedAt: NOW - 10 * MIN,
      connectedAt: NOW - 5 * MIN,
      startedAt: NOW - 60 * MIN,
      hasStoredSession: true,
    }),
    true,
  );
});
