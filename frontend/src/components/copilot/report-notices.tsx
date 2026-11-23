interface ReportNoticesProps {
  /** Set when the report was written by hand for the demo and not by the agents. */
  notice: string | null;
  /** The Critic did not run, so nothing has checked the draft. */
  criticMissing: boolean;
  /** Anything else the screen must say about the report, e.g. that it was written before an override. */
  extra?: string[];
}

/** What a reader must know before relying on the report text. Nothing is shown when there is nothing to say. */
export function ReportNotices({ notice, criticMissing, extra = [] }: ReportNoticesProps) {
  const lines = [
    ...(notice ? [{ key: "notice", text: notice }] : []),
    ...(criticMissing
      ? [{ key: "critic", text: "The Critic's check is not available, so this report has not been checked against the evidence. Re-run the Critic above." }]
      : []),
    ...extra.map((text, i) => ({ key: `extra-${i}`, text })),
  ];
  if (lines.length === 0) return null;
  return (
    <div className="space-y-2">
      {lines.map((l) => (
        <p key={l.key} role="note" className="rounded-xl border border-gold/50 bg-gold/10 px-4 py-3 text-sm text-navy">
          {l.text}
        </p>
      ))}
    </div>
  );
}
