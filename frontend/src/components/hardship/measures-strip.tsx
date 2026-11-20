import { FlagChip } from "@/components/shared/flag-chip";
import { ShowWorkingDrawer } from "@/components/shared/show-working-drawer";
import { measureText } from "@/lib/hardship";
import type { Measure } from "@/lib/hardship-types";
import { workingEvidence } from "@/lib/income";
import { cn } from "@/lib/utils";

interface MeasuresStripProps {
  measures: Measure[];
  caseId: string;
  pillarSlug: string;
}

/** The affordability measures, each with its own Show working drawer. A flagged measure stands out. */
export function MeasuresStrip({ measures, caseId, pillarSlug }: MeasuresStripProps) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {measures.map((m) => (
        <li
          key={m.id}
          data-testid={`measure-${m.id}`}
          className={cn("flex flex-col gap-1 rounded-xl border bg-card p-4", m.flagged && "border-gold bg-gold/10")}
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-xs font-semibold text-muted-foreground">{m.label}</span>
            {m.flagged ? <FlagChip tone="warning">Flagged</FlagChip> : null}
          </div>
          <div className="text-2xl font-semibold text-navy">{measureText(m.value, m.unit)}</div>
          {m.compare ? (
            <div className="text-sm text-muted-foreground">
              {m.compare.label} {measureText(m.compare.value, m.compare.unit)}
            </div>
          ) : null}
          {m.note ? <div className="text-xs text-muted-foreground">{m.note}</div> : null}
          {m.flag_message ? <div className="text-xs font-medium text-navy">{m.flag_message}</div> : null}
          <div className="mt-2">
            <ShowWorkingDrawer
              title={m.label}
              steps={m.working}
              evidence={workingEvidence(m.evidence, pillarSlug, caseId)}
              triggerAriaLabel={`Show working for ${m.label}`}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
