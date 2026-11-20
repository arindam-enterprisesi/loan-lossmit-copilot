import Link from "next/link";
import { FlagChip, severityTone } from "@/components/shared/flag-chip";
import { documentHref, evidenceDetail } from "@/lib/income";
import type { IncomeFlag } from "@/lib/income-types";

interface IncomeFlagCardProps {
  flag: IncomeFlag;
  caseId: string;
  pillarSlug: string;
}

/**
 * One flag: what was found, both values side by side with their sources, then any AI suggestions.
 * Suggestions are always labelled as possible, never as findings.
 */
export function IncomeFlagCard({ flag, caseId, pillarSlug }: IncomeFlagCardProps) {
  return (
    <article className="rounded-xl border bg-card p-4" aria-label={`Flag ${flag.code}`}>
      <div className="flex flex-wrap items-center gap-2">
        <FlagChip tone={severityTone(flag.severity)}>{flag.code}</FlagChip>
        <h3 className="text-base text-navy">{flag.message}</h3>
      </div>

      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        {flag.values.map((v) => (
          <div key={v.label} className="rounded-lg border bg-panel px-3 py-2">
            <dt className="text-xs font-semibold text-muted-foreground">{v.label}</dt>
            <dd className="mt-0.5 text-sm font-semibold text-navy">{v.value}</dd>
            <dd className="mt-0.5 text-xs text-muted-foreground">
              {v.source.document_id ? (
                <Link
                  href={documentHref(pillarSlug, caseId, v.source.document_id)}
                  className="underline underline-offset-2"
                >
                  {v.source.label}
                </Link>
              ) : (
                v.source.label
              )}
              {evidenceDetail(v.source) ? ` · ${evidenceDetail(v.source)}` : ""}
            </dd>
          </div>
        ))}
      </dl>

      {flag.explanations.map((e, i) => (
        <section key={i} className="mt-3 rounded-lg border border-dashed px-3 py-2" aria-label="Suggested explanation">
          <div className="flex flex-wrap items-center gap-2">
            <FlagChip tone="info">{e.label}</FlagChip>
            {!e.figures_verified ? <FlagChip tone="danger">unverified figure</FlagChip> : null}
          </div>
          <p className="mt-1.5 text-sm text-navy">{e.text}</p>
          {e.suggested_documents.length > 0 ? (
            <div className="mt-2">
              <div className="text-xs font-semibold text-muted-foreground">Documents that would settle it</div>
              <ul className="mt-0.5 list-disc pl-5 text-sm text-navy">
                {e.suggested_documents.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ))}
    </article>
  );
}
