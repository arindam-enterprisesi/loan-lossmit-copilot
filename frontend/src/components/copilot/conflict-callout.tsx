import { TriangleAlert } from "lucide-react";
import type { Conflict } from "@/lib/copilot-types";
import { EvidenceLinks } from "./evidence-links";

interface ConflictCalloutProps {
  conflicts: Conflict[];
  caseId: string;
  pillarSlug: string;
}

/**
 * Findings that point different ways, shown openly and not settled by the screen. For Daniel Reyes the DTI is
 * 44.70% with overtime left out and 41.61% if it is counted; the underwriter decides which income to use.
 */
export function ConflictCallout({ conflicts, caseId, pillarSlug }: ConflictCalloutProps) {
  if (conflicts.length === 0) return null;
  return (
    <section aria-labelledby="conflicts-heading" className="space-y-3">
      <h2 id="conflicts-heading" className="text-lg">
        Conflicts between findings
      </h2>
      {conflicts.map((c, i) => (
        <div key={i} role="note" className="space-y-2 rounded-xl border-2 border-gold/60 bg-gold/10 p-4">
          <h3 className="flex items-center gap-2 text-base text-navy">
            <TriangleAlert className="size-4 text-[#7a5f2e]" aria-hidden />
            {c.title}
          </h3>
          {c.figures && c.figures.length > 0 ? (
            <dl className="grid gap-3 sm:grid-cols-2">
              {c.figures.map((f) => (
                <div key={f.label} className="rounded-lg border border-gold/40 bg-card px-3 py-2">
                  <dt className="text-xs font-semibold text-muted-foreground">{f.label}</dt>
                  <dd className="text-xl font-semibold tabular-nums text-navy">{f.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          <p className="text-sm text-navy">{c.detail}</p>
          <EvidenceLinks refs={c.evidence} caseId={caseId} pillarSlug={pillarSlug} />
        </div>
      ))}
    </section>
  );
}
