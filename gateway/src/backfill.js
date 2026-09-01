/**
 * Where to resume reading a group after the gateway has been away.
 *
 * Split out of `index.js` because it is the one piece of arithmetic in this
 * process that can silently lose the firm money in either direction: too far
 * back and it re-extracts a quarter of dead listings, not far back enough and
 * a weekend of inventory is dropped with nothing on screen to say so. Pure
 * functions, so the boundaries can be asserted rather than reasoned about.
 */

/**
 * The oldest message worth forwarding from a group, as an epoch in ms.
 *
 * Two different questions, which used to share one answer:
 *
 *   - "We have ingested this group before" -- then the honest cutoff is the
 *     last thing the CRM stored. Everything after it was posted while this
 *     process was asleep, and is exactly what the owner expects to find
 *     waiting when they link the phone back up.
 *   - "We have never stored anything from this group" -- a group just switched
 *     on, or a fresh pairing. There is no gap to close, only history, so the
 *     fixed age window applies and the scrollback stays out.
 *
 * `backfillMaxAgeMs` is the floor under both. A watermark from six months ago
 * is not a gap, it is an archive.
 *
 * @param entry  the watch-list row for the group, or undefined
 * @param opts   { maxMessageAgeMs, backfillMaxAgeMs, now }
 * @returns      epoch ms; a message at or before this is skipped
 */
export function resumePoint(entry, { maxMessageAgeMs, backfillMaxAgeMs, now }) {
  if (!entry?.lastMessageAt) return now - maxMessageAgeMs;
  // The watermark is a claim about what is already stored, so it is the cutoff
  // on its own -- clamping it to the 24h window would re-forward a day of
  // messages on every reconnect, which the API would only throw away again.
  // The floor is the one thing allowed to override it.
  return Math.max(entry.lastMessageAt, now - backfillMaxAgeMs);
}

/** Parse a watch-list row from the API into what `resumePoint` reads. */
export function watchEntry(group) {
  const parsed = group.last_message_at
    ? Date.parse(group.last_message_at)
    : null;
  return {
    name: group.name,
    // A malformed timestamp must not become NaN and poison every comparison
    // downstream into `false`, which would drop the group's traffic entirely.
    lastMessageAt: Number.isFinite(parsed) ? parsed : null,
  };
}
