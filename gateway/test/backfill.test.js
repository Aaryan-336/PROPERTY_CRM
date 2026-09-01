import assert from "node:assert/strict";
import test from "node:test";

import { resumePoint, watchEntry } from "../src/backfill.js";

const NOW = Date.parse("2026-09-01T12:00:00Z");
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;
const OPTS = { maxMessageAgeMs: DAY, backfillMaxAgeMs: 7 * DAY, now: NOW };

const at = (ms) => new Date(NOW - ms).toISOString();

test("a group the CRM has never stored falls back to the age window", () => {
  assert.equal(resumePoint(undefined, OPTS), NOW - DAY);
  assert.equal(resumePoint({ lastMessageAt: null }, OPTS), NOW - DAY);
});

test("a group with a watermark resumes from it, not from the age window", () => {
  // The whole point: the gateway was down for three days, so three days of
  // messages are owed. The 24h window would have thrown two of them away.
  const entry = watchEntry({ name: "Andheri", last_message_at: at(3 * DAY) });
  assert.equal(resumePoint(entry, OPTS), NOW - 3 * DAY);
});

test("a recent watermark is not widened back to the age window", () => {
  // Reconnecting after a ten minute nap must not re-forward a day of traffic
  // for the API to deduplicate.
  const entry = watchEntry({ name: "Powai", last_message_at: at(10 * 60_000) });
  assert.equal(resumePoint(entry, OPTS), NOW - 10 * 60_000);
});

test("a stale watermark is clamped to the backfill floor", () => {
  // A group dormant since spring is an archive, not a gap.
  const entry = watchEntry({ name: "Old", last_message_at: at(180 * DAY) });
  assert.equal(resumePoint(entry, OPTS), NOW - 7 * DAY);
});

test("a watermark exactly on the floor is kept", () => {
  const entry = watchEntry({ name: "Edge", last_message_at: at(7 * DAY) });
  assert.equal(resumePoint(entry, OPTS), NOW - 7 * DAY);
});

test("a malformed timestamp is treated as no watermark, not as NaN", () => {
  // NaN would make every `timestamp <= cutoff` comparison false, which reads
  // as "forward everything" -- a whole group's scrollback on one bad string.
  const entry = watchEntry({ name: "Broken", last_message_at: "not a date" });
  assert.equal(entry.lastMessageAt, null);
  assert.equal(resumePoint(entry, OPTS), NOW - DAY);
});

test("the cutoff is exclusive of the watermark itself", () => {
  // The watermarked message is already stored. Forwarding it again is only a
  // duplicate, but the boundary is worth pinning: an off-by-one the other way
  // would drop the first genuinely new message after a reconnect.
  const entry = watchEntry({ name: "Bandra", last_message_at: at(HOUR) });
  const cutoff = resumePoint(entry, OPTS);
  assert.ok(!(NOW - HOUR > cutoff), "the watermarked message is skipped");
  assert.ok(NOW - HOUR + 1 > cutoff, "the next message after it is forwarded");
});

test("watchEntry keeps the group name alongside the resume point", () => {
  const entry = watchEntry({ name: "Malad rentals", last_message_at: null });
  assert.equal(entry.name, "Malad rentals");
});
