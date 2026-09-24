"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { MicIcon } from "@/components/icons";
import { NewContactForm } from "@/components/NewContactForm";
import { NewPropertyForm } from "@/components/NewPropertyForm";
import { ChipGroup, Sheet } from "@/components/Sheet";
import type { Role, VoiceDraft, VoiceIntent } from "@/lib/types";

import { UPLOAD_TIMEOUT_MS, explainFailure } from "./errors";
import { type Recording, useRecorder } from "./useRecorder";

const INTENT_OPTIONS: { value: VoiceIntent; label: string; roles: Role[] }[] = [
  { value: "add_lead", label: "New lead", roles: ["owner", "agent", "cold_caller"] },
  { value: "set_reminder", label: "Reminder", roles: ["owner", "agent", "cold_caller"] },
  { value: "add_inventory", label: "Listing", roles: ["owner", "agent"] },
  { value: "log_follow_up", label: "Follow-up", roles: ["owner", "agent"] },
];

/** `datetime-local` wants local wall time with no zone. */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const off = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

/**
 * Speak a lead, listing, reminder or follow-up instead of typing it.
 *
 * Record → Whisper → a draft in the ordinary form. Nothing is saved until the
 * person has read it and pressed that form's own Save, so the AI never writes
 * to the CRM on its own; lead and listing saves go through the same forms
 * (and the same duplicate checks) as typed ones.
 *
 * Opened from the mic in the centre of the dock (AppShell).
 */
export function VoiceSheet({
  role,
  open,
  onClose,
}: {
  role: Role;
  open: boolean;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<"record" | "working" | "review">("record");
  const [draft, setDraft] = useState<VoiceDraft | null>(null);
  const [intent, setIntent] = useState<VoiceIntent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);

  async function upload(rec: Recording | File) {
    setPhase("working");
    setError(null);
    const form = new FormData();
    if (rec instanceof File) form.append("audio", rec, rec.name);
    else form.append("audio", rec.blob, rec.filename);
    const res = await fetch("/api/crm/voice/quick-add", {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => null) : null;
    if (!res?.ok || !body) {
      setError(explainFailure(res, body, "Voice", "Could not process the recording. Try again."));
      setPhase("record");
      return;
    }
    const d = body as VoiceDraft;
    const allowed = INTENT_OPTIONS.filter((o) => o.roles.includes(role)).map((o) => o.value);
    setDraft(d);
    setIntent(allowed.includes(d.intent as VoiceIntent) ? (d.intent as VoiceIntent) : null);
    setPhase("review");
  }

  const recorder = useRecorder(upload);

  function reset() {
    setPhase("record");
    setDraft(null);
    setIntent(null);
    setError(null);
    setShowTranscript(false);
  }

  function close() {
    if (recorder.state === "recording") recorder.stop();
    onClose();
    reset();
  }

  return (
    <>
      <Sheet
        open={open}
        onClose={close}
        title="Add by voice"
        subtitle="Say it the way you would tell a colleague. You check everything before it saves."
      >
        {phase === "record" && (
          <div className="flex flex-col items-center py-4 text-center">
            {recorder.supported ? (
              <>
                <div className="relative flex h-32 w-32 items-center justify-center">
                  {recorder.state === "recording" && (
                    <span
                      aria-hidden
                      className="absolute inset-0 rounded-full bg-sandstone/25 transition-transform duration-75"
                      style={{ transform: `scale(${0.72 + recorder.level * 0.5})` }}
                    />
                  )}
                  <button
                    type="button"
                    onClick={recorder.state === "recording" ? recorder.stop : recorder.start}
                    aria-label={recorder.state === "recording" ? "Stop recording" : "Start recording"}
                    className={`press relative flex h-24 w-24 items-center justify-center rounded-full text-white shadow-float ${
                      recorder.state === "recording" ? "bg-sandstone" : "bg-ink"
                    }`}
                  >
                    {recorder.state === "recording" ? (
                      <span className="h-7 w-7 rounded-md bg-white" />
                    ) : (
                      <MicIcon className="h-10 w-10" />
                    )}
                  </button>
                </div>
                <p className="mt-2 text-sm font-semibold text-ink" aria-live="polite">
                  {recorder.state !== "recording"
                    ? "Tap the mic and speak"
                    : recorder.heard
                      ? `Listening… ${recorder.seconds}s`
                      : "Listening — start speaking"}
                </p>
                <p className="mt-1 text-xs text-slate">
                  {recorder.state === "recording"
                    ? "Pause for two seconds or tap stop when you're done."
                    : "It stops by itself when you pause."}
                </p>
                <p className="mt-4 max-w-xs text-xs text-slate">
                  e.g. &ldquo;New client Rahul, 98200 12345, wants a 2 BHK in Powai to buy,
                  budget 80 lakh to 1.2 crore&rdquo; or &ldquo;Remind me to call Mrs Shah
                  tomorrow at 5&rdquo;.
                </p>
              </>
            ) : (
              <p className="text-sm text-slate">This browser cannot record here. Pick a voice note instead.</p>
            )}
            <label className="tap mt-4 cursor-pointer text-xs font-semibold text-sandstone underline-offset-4 hover:underline">
              Or upload a voice note
              <input
                type="file"
                accept="audio/*"
                className="sr-only"
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              />
            </label>
            {(error || recorder.error) && (
              <p className="mt-3 text-xs font-semibold text-signal">{error ?? recorder.error}</p>
            )}
          </div>
        )}

        {phase === "working" && (
          <div className="py-10 text-center">
            <div className="skeleton mx-auto h-2 w-40 rounded-full" />
            <p className="mt-3 text-sm text-slate">Transcribing and filling in the details…</p>
            <p className="mt-1 text-xs text-slate">Usually a few seconds; longer if the server was asleep.</p>
          </div>
        )}

        {phase === "review" && draft && (
          <div className="space-y-4">
            <div className="rounded-tile bg-parchment-deep px-3.5 py-3">
              <button
                type="button"
                onClick={() => setShowTranscript((v) => !v)}
                className="text-xs font-semibold text-slate"
              >
                {showTranscript ? "Hide" : "Show"} what was heard
              </button>
              {showTranscript && (
                <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{draft.transcript}</p>
              )}
            </div>

            <ChipGroup
              label="What is this?"
              options={INTENT_OPTIONS.filter((o) => o.roles.includes(role))}
              value={intent}
              onChange={setIntent}
              columns={role === "cold_caller" ? 2 : 4}
            />

            {intent === "add_lead" && (
              <NewContactForm
                initial={draft.lead ?? { remarks: draft.transcript }}
              />
            )}
            {intent === "add_inventory" && (
              <NewPropertyForm initial={draft.property ?? undefined} />
            )}
            {intent === "set_reminder" && (
              <ReminderForm
                title={draft.reminder?.title ?? draft.transcript.slice(0, 120)}
                dueAt={draft.reminder?.due_at ?? null}
                onDone={close}
              />
            )}
            {intent === "log_follow_up" && (
              <FollowUpForm
                contactName={draft.follow_up?.contact_name ?? ""}
                note={draft.follow_up?.note ?? draft.transcript}
                onDone={close}
              />
            )}
            {!intent && (
              <p className="text-sm text-slate">Choose what this note is, and the form appears.</p>
            )}

            <button
              type="button"
              onClick={reset}
              className="tap text-xs font-semibold text-sandstone underline-offset-4 hover:underline"
            >
              Record again
            </button>
          </div>
        )}
      </Sheet>
    </>
  );
}

const inputClass =
  "tap w-full rounded-tile border border-hairline bg-card px-4 text-[16px] text-ink outline-none focus:border-ink";

function ReminderForm({
  title: initialTitle,
  dueAt,
  onDone,
}: {
  title: string;
  dueAt: string | null;
  onDone: () => void;
}) {
  const router = useRouter();
  const [title, setTitle] = useState(initialTitle);
  const [due, setDue] = useState(toLocalInput(dueAt));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    if (!title.trim()) {
      setError("Give the reminder a title.");
      return;
    }
    setBusy(true);
    setError(null);
    const res = await fetch("/api/crm/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title: title.trim(),
        due_at: due ? new Date(due).toISOString() : null,
      }),
    }).catch(() => null);
    setBusy(false);
    if (!res?.ok) {
      setError("Could not save the reminder. Try again.");
      return;
    }
    setSaved(true);
    router.refresh();
    setTimeout(onDone, 900);
  }

  if (saved) return <p className="rounded-tile bg-teal-soft px-3.5 py-3 text-sm font-semibold text-teal">Reminder saved.</p>;

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="mb-1.5 block text-xs font-semibold text-slate">Remind me to</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputClass} />
      </label>
      <label className="block">
        <span className="mb-1.5 block text-xs font-semibold text-slate">When</span>
        <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} className={inputClass} />
      </label>
      {error && <p className="text-xs font-semibold text-signal">{error}</p>}
      <button
        type="button"
        onClick={save}
        disabled={busy}
        className="press tap w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white disabled:opacity-60"
      >
        {busy ? "Saving…" : "Save reminder"}
      </button>
    </div>
  );
}

type ContactHit = { id: number; first_name: string; last_name: string | null };

function FollowUpForm({
  contactName,
  note: initialNote,
  onDone,
}: {
  contactName: string;
  note: string;
  onDone: () => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState(contactName);
  const [hits, setHits] = useState<ContactHit[] | null>(null);
  const [picked, setPicked] = useState<ContactHit | null>(null);
  const [note, setNote] = useState(initialNote);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function search() {
    setError(null);
    const res = await fetch(
      `/api/crm/contacts?limit=5&q=${encodeURIComponent(query.trim())}`,
    ).catch(() => null);
    const body = res?.ok ? await res.json().catch(() => null) : null;
    setHits(body?.items ?? []);
  }

  async function save() {
    if (!picked) {
      setError("Pick which lead this is about.");
      return;
    }
    setBusy(true);
    setError(null);
    const res = await fetch("/api/crm/activities", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ contact_id: picked.id, type: "follow_up", body: note.trim() || null }),
    }).catch(() => null);
    setBusy(false);
    if (!res?.ok) {
      setError("Could not log the follow-up. Try again.");
      return;
    }
    setSaved(true);
    router.refresh();
    setTimeout(onDone, 900);
  }

  if (saved) return <p className="rounded-tile bg-teal-soft px-3.5 py-3 text-sm font-semibold text-teal">Follow-up logged.</p>;

  return (
    <div className="space-y-3">
      {picked ? (
        <p className="flex items-center justify-between rounded-tile border border-hairline bg-card px-4 py-3 text-sm">
          <span className="font-semibold text-ink">
            {picked.first_name} {picked.last_name ?? ""}
          </span>
          <button type="button" onClick={() => setPicked(null)} className="text-xs font-semibold text-sandstone">
            Change
          </button>
        </p>
      ) : (
        <div>
          <span className="mb-1.5 block text-xs font-semibold text-slate">Which lead?</span>
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder="Name or phone"
              className={inputClass}
            />
            <button type="button" onClick={search} className="tap rounded-pill bg-ink px-4 text-sm font-semibold text-white">
              Find
            </button>
          </div>
          {hits && (
            <ul className="mt-2 space-y-1.5">
              {hits.length === 0 && <li className="text-xs text-slate">No matching lead in your book.</li>}
              {hits.map((h) => (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => setPicked(h)}
                    className="tap w-full rounded-tile border border-hairline bg-card px-4 text-left text-sm font-semibold text-ink"
                  >
                    {h.first_name} {h.last_name ?? ""}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <label className="block">
        <span className="mb-1.5 block text-xs font-semibold text-slate">What happened</span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} className={`${inputClass} py-3`} />
      </label>
      {error && <p className="text-xs font-semibold text-signal">{error}</p>}
      <button
        type="button"
        onClick={save}
        disabled={busy}
        className="press tap w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white disabled:opacity-60"
      >
        {busy ? "Saving…" : "Log follow-up"}
      </button>
    </div>
  );
}
