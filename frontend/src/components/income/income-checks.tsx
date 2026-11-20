import { FlagChip } from "@/components/shared/flag-chip";
import type { IncomeCheck } from "@/lib/income-types";

/** The cross-document comparisons, each passed or flagged, and the trend sentences built from the numbers. */
export function IncomeChecks({ checks, trend }: { checks: IncomeCheck[]; trend: string[] }) {
  return (
    <div className="space-y-3">
      <ul className="divide-y rounded-xl border bg-card">
        {checks.map((c) => (
          <li key={c.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-3" data-testid={`check-${c.id}`}>
            <FlagChip tone={c.status === "passed" ? "success" : "warning"}>
              {c.status === "passed" ? "Consistent" : "Flagged"}
            </FlagChip>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-navy">{c.label}</div>
              <div className="text-sm text-muted-foreground">{c.detail}</div>
            </div>
          </li>
        ))}
      </ul>
      {trend.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-navy" aria-label="Trend">
          {trend.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
