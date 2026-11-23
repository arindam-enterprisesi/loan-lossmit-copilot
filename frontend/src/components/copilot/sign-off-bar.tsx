"use client";

import { useId, useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { SignOffNote } from "@/components/shared/sign-off-note";
import { Button } from "@/components/ui/button";
import type { ReportStatus, SignOff, SignOffResult } from "@/lib/copilot-types";
import { REASON_MAX } from "@/lib/copilot";
import { formatDate } from "@/lib/format";

interface SignOffBarProps {
  signOffs: SignOff[];
  reportStatus: ReportStatus;
  /** Underwriting only: suggested conditions nobody has reviewed. They are named, and do not stop the sign-off. */
  undecided?: number;
  onSignOff: (note: string) => Promise<SignOffResult>;
}

export const REPORT_STATUS_LABEL: Record<ReportStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  signed_off: "Review signed off",
};

/**
 * "Sign off review. Records a review. Not a decision." It records that a person reviewed this version of the
 * report. It is never a decision about the loan. A change made after a sign-off puts the report back
 * in review and keeps the earlier sign-off, so the bar says so and allows another.
 */
export function SignOffBar({ signOffs, reportStatus, undecided = 0, onSignOff }: SignOffBarProps) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<SignOffResult | null>(null);
  const noteId = useId();

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await onSignOff(note.trim());
      setRecorded(result);
      setNote("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The sign-off could not be recorded.");
    } finally {
      setBusy(false);
    }
  };

  const changedSince = reportStatus === "in_review" && signOffs.length > 0;

  return (
    <section aria-labelledby="sign-off-heading" className="space-y-3 rounded-xl border-2 border-navy/20 bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="sign-off-heading" className="text-lg">
            Sign off review
          </h2>
          <SignOffNote />
        </div>
        <FlagChip tone={reportStatus === "signed_off" ? "success" : reportStatus === "in_review" ? "info" : "neutral"}>
          {REPORT_STATUS_LABEL[reportStatus]}
        </FlagChip>
      </div>

      {undecided > 0 ? (
        <p role="note" className="rounded-lg border border-gold/50 bg-gold/10 px-3 py-2 text-sm text-navy">
          {undecided === 1 ? "1 suggested condition has" : `${undecided} suggested conditions have`} not been reviewed. You can still sign off; the
          record will say how many were left.
        </p>
      ) : null}
      {changedSince ? (
        <p role="note" className="rounded-lg border border-gold/50 bg-gold/10 px-3 py-2 text-sm text-navy">
          The report changed after the last sign-off. Sign off again to record that you reviewed this version.
        </p>
      ) : null}

      <div className="grid gap-1">
        <label htmlFor={noteId} className="text-xs font-semibold text-muted-foreground">
          Note (optional)
        </label>
        <textarea
          id={noteId}
          rows={2}
          maxLength={REASON_MAX}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={busy}
          className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={submit} disabled={busy}>
          Sign off review
        </Button>
        {recorded ? (
          <span role="status" className="text-sm text-success">
            Review recorded.
            {recorded.pending_conditions > 0
              ? ` ${recorded.pending_conditions} suggested ${recorded.pending_conditions === 1 ? "condition was" : "conditions were"} left unreviewed.`
              : ""}
          </span>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}

      {signOffs.length > 0 ? (
        <div>
          <h3 className="text-sm text-navy">Earlier sign-offs</h3>
          <ul aria-label="Sign-offs" className="mt-1 space-y-1 text-sm text-muted-foreground">
            {signOffs.map((s) => (
              <li key={s.id}>
                {s.signed_by} · {formatDate(s.signed_at)} · version {s.report_version}
                {s.note ? ` · ${s.note}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
