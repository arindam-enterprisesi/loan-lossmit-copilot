import { FlagChip } from "@/components/shared/flag-chip";
import type { Finding } from "@/lib/copilot-types";
import { groupByPriority, PRIORITY_LABEL, PRIORITY_NOTE, PRIORITY_TONE } from "@/lib/copilot";
import { EvidenceLinks } from "./evidence-links";

interface FindingsListProps {
  findings: Finding[];
  caseId: string;
  pillarSlug: string;
  onOpenPassage?: (passageId: string) => void;
}

/**
 * Findings grouped by priority: significant, attention, then information. Priority is the order to review in,
 * and says nothing about whether the loan can go ahead. Every finding shows where it came from.
 */
export function FindingsList({ findings, caseId, pillarSlug, onOpenPassage }: FindingsListProps) {
  if (findings.length === 0) return <p className="text-sm text-muted-foreground">No findings.</p>;
  return (
    <div className="space-y-5">
      <p className="text-xs text-muted-foreground">{PRIORITY_NOTE}</p>
      {groupByPriority(findings).map(({ priority, items }) => (
        <section key={priority} aria-label={`${PRIORITY_LABEL[priority]} findings`} className="space-y-2">
          <h3 className="flex items-center gap-2 text-base text-navy">
            <FlagChip tone={PRIORITY_TONE[priority]}>{PRIORITY_LABEL[priority]}</FlagChip>
            <span className="text-sm font-normal text-muted-foreground">
              {items.length} {items.length === 1 ? "finding" : "findings"}
            </span>
          </h3>
          <ul className="space-y-2">
            {items.map((f) => (
              <li key={f.id}>
                <article aria-label={f.title} className="space-y-1.5 rounded-xl border bg-card p-4">
                  <h4 className="text-sm font-semibold text-navy">{f.title}</h4>
                  <p className="text-sm text-muted-foreground">{f.detail}</p>
                  <EvidenceLinks refs={f.evidence} caseId={caseId} pillarSlug={pillarSlug} onOpenPassage={onOpenPassage} />
                </article>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
