/**
 * Whether a queued "Connect WhatsApp" press should be allowed to wipe the
 * session on disk.
 *
 * One button, two meanings, told apart only by when it was pressed:
 *
 *   - Pressed at a screen showing a linked account, it means "link a different
 *     phone". The screen asks twice before sending it.
 *   - Pressed at a screen showing nothing connected, it means "you are dead,
 *     wake up". The screen does not ask at all, because as far as it knows
 *     there is nothing to lose.
 *
 * But the CRM cannot see the gateway's disk. A gateway that was merely not
 * running still holds a perfectly good session, and the second kind of press
 * then destroys it -- the owner is asked to scan a QR to fix a gateway that
 * had already fixed itself. An unnecessary relink is the most account-flagging
 * thing this process does, so the bar for doing one is deliberately high.
 */

/**
 * @param opts.pairRequestedAt  when the owner pressed it, epoch ms, or null
 * @param opts.connectedAt      when the current socket came up, or null
 * @param opts.startedAt        when this process started, epoch ms
 * @param opts.hasStoredSession whether creds exist on disk right now
 * @returns true to ignore the request and keep the existing session
 */
export function shouldIgnorePairRequest({
  pairRequestedAt,
  connectedAt,
  startedAt,
  hasStoredSession,
}) {
  // Nothing to protect. Whatever the press meant, pairing is the only useful
  // response -- and refusing here would strand a first-time setup forever.
  if (!hasStoredSession) return false;

  // An undated request cannot be placed, and the safe reading of "cannot tell"
  // is the one that does not destroy a working login.
  if (!pairRequestedAt) return true;

  // The moment this gateway could first have been described as alive. Falling
  // back to process start is what closes the cold-start hole: for the first few
  // seconds of a run `connectedAt` is still null, and a guard that only
  // consulted it would wave through every stale request queued while the
  // process was down -- which is precisely when they pile up.
  const aliveSince = connectedAt ?? startedAt;
  return pairRequestedAt < aliveSince;
}
