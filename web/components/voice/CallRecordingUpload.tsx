"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field, inputClass } from "@/components/forms";
import { UploadIcon } from "@/components/icons";
import { DateTimeField, fromLocalInput, toLocalInput } from "@/components/reminders/DateTimeField";
import { ChipGroup } from "@/components/Sheet";
import { Card, SectionHeading } from "@/components/ui";
import type { CallRecordingDraft } from "@/lib/types";

import { UPLOAD_TIMEOUT_MS, explainFailure } from "./errors";
import { CALL_OUTCOMES, TEMPERATURES } from "@/lib/types";

// Uploads travel through this app's own server so the session token never
// reaches the browser, and Vercel caps a request body at ~4.5 MB.
const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

type Outcome = CallRecordingDraft["outcome"];
type Temperature = NonNullable<CallRecordingDraft["temperature"]>;

/**
 * Upload a recording of a call (from the phone's recorder or call-recording
 * app) and get the remark written for you: summary, outcome, temperature and
 * a suggested follow-up. It is only a draft until "Save to call log", which
 * goes through the same POST /calls as a typed remark.
 *
 * Deliberately a manual upload: iOS does not let apps record calls, and
 * Android support varies by manufacturer.
 */
export function CallRecordingUpload({ contactId }: { contactId: number }) {
  const router = useRouter();
  const [phase, setPhase] = useState<"idle" | "working" | "review" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<CallRecordingDraft | null>(null);
  const [outcome, setOutcome] = useState<Outcome>("connected");
  const [temperature, setTemperature] = useState<Temperature | null>(null);
  const [notes, setNotes] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [showTranscript, setShowTranscript] = useState(false);
  const [busy, setBusy] = useState(false);

  async function upload(file: File) {
    setError(null);
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(
        "That file is over 4 MB, the most the app can pass through today. Trim the recording or export it at a lower quality.",
      );
      return;
    }
    setPhase("working");
    const form = new FormData();
    form.append("audio", file, file.name);
    const res = await fetch(`/api/crm/calls/${contactId}/recording`, {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => null) : null;
    if (!res?.ok || !body) {
      setError(
        explainFailure(res, body, "Call transcription", "Could not transcribe that recording. Try again."),
      );
      setPhase("idle");
      return;
    }
    const d = body as CallRecordingDraft;
    setDraft(d);
    setOutcome(d.outcome);
    setTemperature(d.temperature);
    setNotes([d.summary, d.follow_up_note ? `Next: ${d.follow_up_note}` : ""].filter(Boolean).join("\n"));
    setFollowUp(toLocalInput(d.follow_up_at));
    setPhase("review");
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    const res = await fetch("/api/crm/calls", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        contact_id: contactId,
        outcome,
        temperature,
        notes: notes.trim() || null,
        follow_up_at: fromLocalInput(followUp),
        transcript: draft.transcript,
      }),
    }).catch(() => null);
    setBusy(false);
    if (!res?.ok) {
      const body = await res?.json().catch(() => null);
      setError(body?.error?.message ?? "Could not save to the call log.");
      return;
    }
    setPhase("saved");
    router.refresh();
  }

  function reset() {
    setPhase("idle");
    setDraft(null);
    setError(null);
    setShowTranscript(false);
  }

  return (
    <Card className="p-5">
      <SectionHeading
        title="Call recording"
        hint="Upload a recorded call and the remark is drafted for you to check."
      />

      {phase === "idle" && (
        <label className="press tap inline-flex cursor-pointer items-center gap-2 rounded-pill border border-hairline bg-card px-4 text-sm font-semibold text-ink">
          <UploadIcon className="h-4 w-4" />
          Upload recording
          <input
            type="file"
            accept="audio/*,.m4a,.mp3,.aac,.amr,.ogg,.wav,.3gp"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) upload(f);
            }}
          />
        </label>
      )}

      {phase === "working" && (
        <div className="py-4">
          <div className="skeleton h-2 w-40 rounded-full" />
          <p className="mt-3 text-sm text-slate">Transcribing and summarising the call…</p>
        </div>
      )}

      {phase === "review" && draft && (
        <div className="space-y-4">
          <ChipGroup label="Outcome" options={CALL_OUTCOMES} value={outcome} onChange={(v) => v && setOutcome(v)} columns={3} />
          <ChipGroup label="Temperature" options={TEMPERATURES} value={temperature} onChange={setTemperature} columns={3} allowClear />
          <Field label="Remark">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={5}
              className={`${inputClass} resize-y py-3 leading-relaxed`}
            />
          </Field>
          <div>
            <span className="mb-1.5 block text-xs font-semibold text-slate">Follow up</span>
            <DateTimeField value={followUp} onChange={setFollowUp} />
          </div>
          <div className="rounded-tile bg-parchment-deep px-3.5 py-3">
            <button type="button" onClick={() => setShowTranscript((v) => !v)} className="text-xs font-semibold text-slate">
              {showTranscript ? "Hide" : "Show"} full transcript
            </button>
            {showTranscript && (
              <p className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap text-sm text-ink">{draft.transcript}</p>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="press tap flex-1 rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save to call log"}
            </button>
            <button type="button" onClick={reset} disabled={busy} className="tap rounded-pill border border-hairline bg-card px-4 text-sm font-semibold text-ink">
              Discard
            </button>
          </div>
        </div>
      )}

      {phase === "saved" && (
        <div className="flex items-center justify-between gap-3 rounded-tile bg-teal-soft px-3.5 py-3">
          <p className="text-sm font-semibold text-teal">Saved to the call log.</p>
          <button type="button" onClick={reset} className="text-xs font-semibold text-teal underline-offset-4 hover:underline">
            Upload another
          </button>
        </div>
      )}

      {error && <p className="mt-3 text-xs font-semibold text-signal">{error}</p>}
    </Card>
  );
}
