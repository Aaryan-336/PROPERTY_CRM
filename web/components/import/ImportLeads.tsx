"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { PlusIcon } from "@/components/icons";
import {
  Card,
  InkCard,
  MetricTile,
  SectionHeading,
  StatusPill,
  type Tone,
} from "@/components/ui";
import { roleLabel } from "@/lib/format";
import type { ImportPreview, ImportResult, UserWorkload } from "@/lib/types";

const ROW_TONE: Record<string, Tone> = {
  new: "positive",
  duplicate: "neutral",
  invalid: "signal",
};

/**
 * Upload a calling list, decide who works it.
 *
 * Two steps on purpose. These files arrive as portal exports and purchased
 * lists with no agreed shape, so the owner sees which column was read as the
 * phone number — and how many rows are already in the system — before any of
 * it lands in somebody's queue. Getting that wrong is expensive to undo: it
 * means a caller working a list of unreachable numbers, or ringing the same
 * person twice.
 */
export function ImportLeads({ staff }: { staff: UserWorkload[] }) {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  // Anyone who can work a queue. Agents are included because a lead assigned
  // to an agent lands in their own list — the owner may well be handing an
  // imported list to a closer rather than a caller.
  const assignable = staff.filter(
    (s) => !s.user.deleted_at && s.user.role !== "owner",
  );

  function reset() {
    setFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
    setSelected([]);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function runPreview(chosen: File) {
    setBusy("preview");
    setError(null);
    setResult(null);

    const body = new FormData();
    body.append("file", chosen);

    const res = await fetch("/api/crm/contacts/bulk-import/preview", {
      method: "POST",
      body,
    }).catch(() => null);

    if (!res || !res.ok) {
      const payload = await res?.json().catch(() => null);
      setError(payload?.error?.message ?? "Could not read that file.");
      setPreview(null);
      setBusy(null);
      return;
    }
    setPreview(await res.json());
    setBusy(null);
  }

  async function runImport() {
    if (!file) return;
    if (selected.length === 0) {
      setError("Choose at least one person to receive these leads.");
      return;
    }
    setBusy("import");
    setError(null);

    const body = new FormData();
    body.append("file", file);
    for (const id of selected) body.append("assign_to", String(id));

    const res = await fetch("/api/crm/contacts/bulk-import", {
      method: "POST",
      body,
    }).catch(() => null);

    if (!res || !res.ok) {
      const payload = await res?.json().catch(() => null);
      setError(payload?.error?.message ?? "Import failed.");
      setBusy(null);
      return;
    }

    setResult(await res.json());
    setBusy(null);
    router.refresh();
  }

  function toggle(id: number) {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : [...current, id],
    );
  }

  // Round-robin, mirroring app/lead_import.distribute — so the owner can see
  // the split before committing rather than after.
  function share(index: number): number {
    if (!preview || selected.length === 0) return 0;
    const total = preview.importable;
    return Math.floor(total / selected.length) + (index < total % selected.length ? 1 : 0);
  }

  return (
    <div className="space-y-5">
      <InkCard className="p-5 lg:p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
          Cold calling
        </p>
        <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
          Import a calling list
        </h1>
        <p className="mt-1 text-sm text-ink-dim">
          Upload an Excel or CSV file of names and numbers, then choose who
          calls them. Assigned leads appear in that person&rsquo;s queue
          straight away.
        </p>
      </InkCard>

      {/* ---------------------------------------------------------- step 1 */}
      <Card className="p-5">
        <SectionHeading
          title="1 · Choose a file"
          hint="Excel (.xlsx) or CSV — headers are detected automatically"
        />

        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.xlsm,.csv,.tsv,text/csv"
          className="sr-only"
          onChange={(e) => {
            const chosen = e.target.files?.[0] ?? null;
            setFile(chosen);
            setResult(null);
            if (chosen) runPreview(chosen);
          }}
        />

        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="tap flex w-full items-center justify-center gap-2 rounded-tile border border-dashed border-hairline bg-parchment px-5 py-6 text-sm font-semibold text-ink"
        >
          <PlusIcon className="h-4 w-4" />
          {file ? file.name : "Select a spreadsheet"}
        </button>

        {file && (
          <button
            type="button"
            onClick={reset}
            className="mt-2 text-xs font-semibold text-slate"
          >
            Clear
          </button>
        )}

        <p className="mt-3 text-[11px] leading-relaxed text-slate">
          Any column layout works. A sheet with <code className="tabular">Name</code>{" "}
          and <code className="tabular">Mobile</code>, one with{" "}
          <code className="tabular">Client Name</code> and{" "}
          <code className="tabular">Contact No.</code>, or one with no header row
          at all are all read correctly.
        </p>
      </Card>

      {busy === "preview" && (
        <p className="text-sm text-slate">Reading the file…</p>
      )}

      {/* ---------------------------------------------------------- step 2 */}
      {preview && !result && (
        <>
          <Card className="p-5">
            <SectionHeading
              title="2 · Check what was found"
              hint={
                preview.header_row
                  ? `Header detected on row ${preview.header_row}`
                  : "No header row — columns identified from their values"
              }
            />

            <div className="mb-4 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
              <MetricTile label="Rows in file" value={preview.total_rows} />
              <MetricTile label="Will import" value={preview.importable} />
              <MetricTile
                label="Already known"
                value={preview.duplicates}
                sub={preview.duplicates ? "skipped" : "none"}
              />
              <MetricTile
                label="Unusable"
                value={preview.invalid}
                sub={preview.invalid ? "no valid number" : "none"}
              />
            </div>

            {preview.warnings.map((warning) => (
              <p
                key={warning}
                className="mb-2 rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal"
              >
                {warning}
              </p>
            ))}

            <div className="mb-4 flex flex-wrap gap-1.5">
              {Object.entries(preview.detected_columns).map(([field, column]) => (
                <span
                  key={field}
                  className="rounded-pill bg-parchment-deep px-2.5 py-1 text-[11px] font-semibold text-slate"
                >
                  {field.replace(/_/g, " ")} ← <span className="tabular">{column}</span>
                </span>
              ))}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[440px] text-sm">
                <thead>
                  <tr className="border-b border-hairline text-left">
                    {["Row", "Name", "Phone", "Status"].map((h) => (
                      <th
                        key={h}
                        className="px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {preview.sample.map((row) => (
                    <tr key={row.row_number}>
                      <td className="tabular px-2 py-2 text-slate">{row.row_number}</td>
                      <td className="px-2 py-2 text-ink">{row.name}</td>
                      <td className="tabular px-2 py-2 text-slate">{row.phone}</td>
                      <td className="px-2 py-2">
                        <StatusPill
                          label={row.status}
                          tone={ROW_TONE[row.status] ?? "neutral"}
                        />
                        {row.detail && (
                          <span className="ml-1 text-[11px] text-slate">
                            {row.detail}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.total_rows > preview.sample.length && (
              <p className="mt-2 text-[11px] text-slate">
                Showing the first {preview.sample.length} of {preview.total_rows}{" "}
                rows.
              </p>
            )}
          </Card>

          {/* -------------------------------------------------------- step 3 */}
          <Card className="p-5">
            <SectionHeading
              title="3 · Assign the leads"
              hint="Tick everyone who should get a share. Rows are dealt out evenly."
            />

            {assignable.length === 0 ? (
              <p className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
                There are no cold callers or agents to assign to. Add staff on
                the Team screen first.
              </p>
            ) : (
              <ul className="space-y-2">
                {assignable.map((member) => {
                  const checked = selected.includes(member.user.id);
                  const index = selected.indexOf(member.user.id);
                  return (
                    <li key={member.user.id}>
                      <label
                        className={`tap flex cursor-pointer items-center gap-3 rounded-tile border px-4 py-3 transition-colors ${
                          checked
                            ? "border-ink bg-ink text-white"
                            : "border-hairline bg-card text-ink"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggle(member.user.id)}
                          className="h-5 w-5 shrink-0 accent-sandstone"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold">
                            {member.user.name}
                          </span>
                          <span
                            className={`block truncate text-xs ${checked ? "text-ink-dim" : "text-slate"}`}
                          >
                            {roleLabel(member.user.role)} ·{" "}
                            {member.active_leads} live leads
                          </span>
                        </span>
                        {checked && (
                          <span className="tabular shrink-0 rounded-pill bg-sandstone px-2.5 py-1 text-[11px] font-semibold text-white">
                            +{share(index)}
                          </span>
                        )}
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}

            {error && (
              <p
                role="alert"
                className="mt-4 rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal"
              >
                {error}
              </p>
            )}

            <button
              type="button"
              onClick={runImport}
              disabled={busy !== null || preview.importable === 0 || selected.length === 0}
              className="tap mt-4 w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50"
            >
              {busy === "import"
                ? "Importing…"
                : preview.importable === 0
                  ? "Nothing to import"
                  : `Import ${preview.importable} lead${preview.importable === 1 ? "" : "s"}`}
            </button>
            <p className="mt-2 text-center text-[11px] text-slate">
              Leads already in the system are skipped automatically.
            </p>
          </Card>
        </>
      )}

      {/* ---------------------------------------------------------- result */}
      {result && (
        <Card className="p-5">
          <SectionHeading title="Imported" hint="These leads are in the queue now" />
          <div className="mb-4 grid grid-cols-3 gap-2.5">
            <MetricTile label="Imported" value={result.imported} />
            <MetricTile label="Already known" value={result.duplicates} />
            <MetricTile label="Unusable" value={result.invalid} />
          </div>
          <ul className="divide-y divide-hairline">
            {result.assignments.map((a) => (
              <li
                key={a.user_id}
                className="flex items-center justify-between gap-3 py-2.5"
              >
                <span className="truncate text-sm text-ink">{a.name}</span>
                <span className="tabular shrink-0 text-sm font-semibold text-ink">
                  {a.assigned} lead{a.assigned === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={reset}
            className="tap mt-4 w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white"
          >
            Import another list
          </button>
        </Card>
      )}
    </div>
  );
}
