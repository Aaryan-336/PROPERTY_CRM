"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AddGroupForm } from "@/components/feed/AddGroupForm";
import { ChevronRight, PlusIcon } from "@/components/icons";
import {
  Card,
  EmptyState,
  InkCard,
  MetricTile,
  SectionHeading,
  StatusPill,
  type Tone,
} from "@/components/ui";
import { money, relativeTime } from "@/lib/format";
import {
  INGEST_STATUS_LABELS,
  type IngestionStatus,
  type Property,
  type WhatsAppGroup,
  type WhatsAppMessage,
} from "@/lib/types";

const STATUS_TONE: Record<string, Tone> = {
  extracted: "positive",
  duplicate: "neutral",
  not_listing: "neutral",
  pending: "warning",
  processing: "warning",
  failed: "signal",
};

/**
 * The owner's view of the WhatsApp feed.
 *
 * Built around the two questions the owner will actually ask: "is it running?"
 * and "is it producing anything useful?". Both are easy to get wrong silently
 * — a dropped WhatsApp session and an unset API key both look identical from
 * the inventory list (nothing new appears), so each has its own explicit
 * banner rather than being left to inference from a zero.
 */
export function FeedConsole({
  status,
  groups,
  recent,
  needsReview,
}: {
  status: IngestionStatus;
  groups: WhatsAppGroup[];
  recent: WhatsAppMessage[];
  needsReview: Property[];
}) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function call(path: string, method: string, body?: unknown) {
    setBusyId(-1);
    await fetch(`/api/crm/${path}`, {
      method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    setBusyId(null);
    router.refresh();
  }

  // Three distinct conditions, deliberately not collapsed. "No key",
  // "nothing running" and "running but behind" all look identical from the
  // inventory list — it simply stops growing — and each has a different fix.
  const stalled = status.pending > 0 && !status.extraction_configured;
  const nothingRunning = status.extraction_configured && !status.extractor_running;
  const quiet =
    status.groups_active > 0 &&
    status.messages_last_24h === 0 &&
    Boolean(status.last_message_at);

  return (
    <div className="space-y-5">
      <InkCard className="p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
              WhatsApp
            </p>
            <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
              Inventory feed
            </h1>
            <p className="mt-1 text-sm text-ink-dim">
              {status.groups_active} of {status.groups_total} group
              {status.groups_total === 1 ? "" : "s"} monitored
              {status.last_message_at
                ? ` · last message ${relativeTime(status.last_message_at)}`
                : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="tap flex items-center gap-2 rounded-pill bg-sandstone px-5 text-sm font-semibold text-white"
          >
            <PlusIcon className="h-4 w-4" />
            Add group
          </button>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <MetricTile
            label="Messages 24h"
            value={status.messages_last_24h}
            ink
          />
          <MetricTile
            label="Listings found"
            value={status.properties_from_whatsapp}
            sub="all time"
            ink
          />
          <MetricTile
            label="Reposts merged"
            value={status.duplicates_merged}
            sub="not duplicated"
            ink
          />
          <MetricTile
            label="Queued"
            value={status.pending}
            sub={status.failed_last_24h ? `${status.failed_last_24h} failed` : "waiting"}
            ink
          />
        </div>
      </InkCard>

      {/* Two silent failure modes, each stated plainly rather than left to be
          inferred from an inventory list that simply stopped growing. */}
      {!status.extraction_configured && (
        <Banner tone="signal">
          <strong>Extraction is not configured.</strong> Messages are being
          stored but nothing is being turned into inventory. Set{" "}
          <code className="tabular">GROQ_API_KEY</code> where the API runs.
          {stalled && ` ${status.pending} message(s) are waiting.`}
        </Banner>
      )}

      {nothingRunning && (
        <Banner tone="signal">
          <strong>Nothing is reading the queue.</strong> The model key is set,
          but no extraction loop has reported in
          {status.extractor_seen_at
            ? ` since ${relativeTime(status.extractor_seen_at)}`
            : " — ever"}
          .{" "}
          {status.pending > 0
            ? `${status.pending} message${status.pending === 1 ? "" : "s"} will stay queued until one runs.`
            : "Messages will queue as they arrive."}{" "}
          Either run the worker service, or set{" "}
          <code className="tabular">EXTRACTION_IN_API=true</code> on the API and
          restart it.
        </Banner>
      )}

      {status.extractor_running && status.pending > 20 && (
        <Banner tone="warning">
          <strong>{status.pending} messages are queued.</strong> The extractor
          is running{status.extractor_note ? ` (${status.extractor_note})` : ""}{" "}
          and working through a backlog. On Groq&rsquo;s free tier this is
          slow rather than stuck.
        </Banner>
      )}

      {quiet && (
        <Banner tone="warning">
          <strong>No messages in 24 hours.</strong> The groups are quiet, or the
          gateway lost its WhatsApp session. Check the gateway logs — it may
          need re-pairing.
        </Banner>
      )}

      {status.stalled > 0 && (
        <Banner tone="warning">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-2">
            <span>
              <strong>
                {status.stalled} message{status.stalled === 1 ? "" : "s"} stuck on
                extracting.
              </strong>{" "}
              A worker took {status.stalled === 1 ? "it" : "them"} and stopped
              before finishing — usually the free plan suspending the API. A
              running worker frees these on its own; if none is running, this
              does it now.
            </span>
            <button
              type="button"
              disabled={busyId !== null}
              onClick={() => call("whatsapp/reprocess-failed", "POST")}
              className="tap rounded-pill bg-ink px-4 text-xs font-semibold text-white disabled:opacity-50"
            >
              Requeue
            </button>
          </span>
        </Banner>
      )}

      {status.failed_last_24h > 0 && (
        <Banner tone="signal">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-2">
            <span>
              {status.failed_last_24h} message
              {status.failed_last_24h === 1 ? "" : "s"} could not be read in the
              last 24 hours.
            </span>
            {/* One press for the whole backlog. Retrying individually is right
                when one message is odd, and useless when extraction was
                misconfigured and every message failed for the same reason. */}
            <button
              type="button"
              disabled={busyId !== null}
              onClick={() => call("whatsapp/reprocess-failed", "POST")}
              className="tap rounded-pill bg-ink px-4 text-xs font-semibold text-white disabled:opacity-50"
            >
              Retry all
            </button>
          </span>
        </Banner>
      )}

      <div className="grid gap-5 [&>*]:min-w-0 lg:grid-cols-[1fr_380px]">
        <div className="space-y-5">
          <Card className="p-5">
            <SectionHeading
              title="Monitored groups"
              hint="Only these are ever read"
            />
            {groups.length === 0 ? (
              <EmptyState
                title="No groups yet. Run `npm run groups` in the gateway to list the group ids this account can see, then add them here."
              />
            ) : (
              <ul className="divide-y divide-hairline">
                {groups.map((group) => (
                  <li
                    key={group.id}
                    className="flex items-center justify-between gap-3 py-3"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-semibold text-ink">
                          {group.name}
                        </p>
                        {!group.is_active && (
                          <StatusPill label="Paused" tone="neutral" />
                        )}
                      </div>
                      <p className="tabular truncate text-[11px] text-slate">
                        {group.message_count} messages · {group.listing_count}{" "}
                        listings
                        {group.pending_count
                          ? ` · ${group.pending_count} queued`
                          : ""}
                        {group.last_message_at
                          ? ` · ${relativeTime(group.last_message_at)}`
                          : " · nothing yet"}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() =>
                          call(`whatsapp/groups/${group.id}`, "PATCH", {
                            is_active: !group.is_active,
                          })
                        }
                        className="text-xs font-semibold text-sandstone-deep disabled:opacity-50"
                      >
                        {group.is_active ? "Pause" : "Resume"}
                      </button>
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() =>
                          call(`whatsapp/groups/${group.id}`, "DELETE")
                        }
                        className="text-xs font-semibold text-signal disabled:opacity-50"
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-[11px] leading-relaxed text-slate">
              Removing a group stops new messages. Listings already sourced from
              it stay in inventory, with their history intact.
            </p>
          </Card>

          <Card className="p-5">
            <SectionHeading
              title="Recent messages"
              hint="What the feed made of each one"
            />
            {recent.length === 0 ? (
              <EmptyState title="Nothing received yet. Make sure the gateway is running and paired." />
            ) : (
              <ul className="space-y-2.5">
                {recent.map((message) => (
                  <li
                    key={message.id}
                    className="rounded-tile border border-hairline bg-parchment px-3.5 py-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="line-clamp-3 min-w-0 flex-1 whitespace-pre-wrap text-xs leading-relaxed text-ink">
                        {message.body}
                      </p>
                      <StatusPill
                        label={
                          INGEST_STATUS_LABELS[message.status] ?? message.status
                        }
                        tone={STATUS_TONE[message.status] ?? "neutral"}
                      />
                    </div>
                    <div className="tabular mt-2 flex flex-wrap items-center gap-x-2 text-[11px] text-slate">
                      <span>{message.group_name ?? "—"}</span>
                      {message.sender_name && <span>· {message.sender_name}</span>}
                      <span>· {relativeTime(message.received_at)}</span>
                      {message.listings_found > 0 && (
                        <span>
                          · {message.listings_found} listing
                          {message.listings_found === 1 ? "" : "s"}
                          {message.listings_new === 0 && " (all reposts)"}
                        </span>
                      )}
                      {/* Offered on every message, not just failed ones.
                          Storing raw bodies before parsing exists precisely so
                          an improved prompt can be replayed over history — and
                          the messages that most need replaying are the ones
                          that "succeeded" and got it wrong, which by definition
                          never reach the failed state. */}
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() =>
                          call(`whatsapp/reprocess/${message.id}`, "POST")
                        }
                        className="font-semibold text-sandstone-deep disabled:opacity-50"
                      >
                        · {message.status === "failed" ? "Retry" : "Re-extract"}
                      </button>
                    </div>
                    {message.error && (
                      <p className="mt-1 truncate text-[11px] text-signal">
                        {message.error}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          {/* The review queue is the honest half of "publish low-confidence
              extractions": they reach inventory, but the owner is told which
              ones the extractor was unsure about. */}
          <InkCard className="p-5">
            <SectionHeading
              title="Needs a look"
              hint="Published, but the extractor was unsure"
              ink
              action={
                status.needs_review > 0 ? (
                  <StatusPill label={`${status.needs_review}`} tone="signal" />
                ) : undefined
              }
            />
            {needsReview.length === 0 ? (
              <p className="py-4 text-sm text-ink-dim">
                Nothing flagged. Listings the extractor was confident about go
                straight into inventory.
              </p>
            ) : (
              <ul className="space-y-2.5">
                {needsReview.map((prop) => (
                  <li key={prop.id} className="rounded-tile bg-ink-soft p-3.5">
                    <Link
                      href={`/properties/${prop.id}`}
                      className="block text-sm font-semibold text-white"
                    >
                      {prop.title ?? `${prop.bhk ?? "?"}BHK in ${prop.location}`}
                    </Link>
                    <p className="tabular mt-0.5 text-[11px] text-ink-muted">
                      {money(prop.price)} ·{" "}
                      {prop.listing_type === "rent" ? "Rent" : "Sale"}
                      {prop.source_group ? ` · ${prop.source_group}` : ""}
                    </p>
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() =>
                          call(`properties/${prop.id}/review`, "POST", {
                            review_state: "confirmed",
                          })
                        }
                        className="tap flex-1 rounded-pill bg-teal px-3 text-xs font-semibold text-white disabled:opacity-50"
                      >
                        Looks right
                      </button>
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={() =>
                          call(`properties/${prop.id}/review`, "POST", {
                            review_state: "rejected",
                          })
                        }
                        className="tap flex-1 rounded-pill border border-ink-line px-3 text-xs font-semibold text-ink-dim disabled:opacity-50"
                      >
                        Discard
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </InkCard>

          <Card className="p-5">
            <SectionHeading title="How it works" />
            <ol className="space-y-3 text-xs leading-relaxed text-slate">
              <Step n={1}>
                The gateway watches the groups above and forwards every message.
              </Step>
              <Step n={2}>
                Each message is stored raw first, so a parsing fix can be
                replayed over history rather than the message being lost.
              </Step>
              <Step n={3}>
                The extractor reads it in any format, decides whether it is
                actually inventory, and pulls out location, building, BHK, price
                and area.
              </Step>
              <Step n={4}>
                A repost of a flat already in inventory is merged into the
                existing row instead of duplicating it — {status.duplicates_merged}{" "}
                so far.
              </Step>
            </ol>
            <Link
              href="/properties?source=whatsapp_group"
              className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
            >
              See what the feed has produced
              <ChevronRight className="h-3.5 w-3.5" />
            </Link>
          </Card>
        </div>
      </div>

      <AddGroupForm open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: "signal" | "warning";
  children: React.ReactNode;
}) {
  return (
    <p
      className={`rounded-card border px-4 py-3 text-sm leading-relaxed ${
        tone === "signal"
          ? "border-signal/40 bg-signal-soft text-signal"
          : "border-sandstone/40 bg-sandstone-soft text-sandstone-deep"
      }`}
    >
      {children}
    </p>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <span className="tabular flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ink text-[10px] font-semibold text-white">
        {n}
      </span>
      <span>{children}</span>
    </li>
  );
}
