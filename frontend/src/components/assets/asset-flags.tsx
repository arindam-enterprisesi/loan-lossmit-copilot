import Link from "next/link";
import { FlagChip, severityTone } from "@/components/shared/flag-chip";
import type { AssetFlag } from "@/lib/assets-types";
import { documentHref, evidenceDetail } from "@/lib/income";

/** The flags found in the statements and the figures: what was found, and where. A flag is a prompt to look, not a decision. */
export function AssetFlags({ flags, caseId, pillarSlug }: { flags: AssetFlag[]; caseId: string; pillarSlug: string }) {
  if (flags.length === 0) {
    return <p className="rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground">Nothing flagged.</p>;
  }
  return (
    <ul className="space-y-3">
      {flags.map((f, i) => (
        <li key={`${f.code}-${i}`} className="rounded-xl border bg-card p-4" data-testid={`flag-${f.code}`}>
          <div className="flex flex-wrap items-center gap-2">
            <FlagChip tone={severityTone(f.severity)}>{f.code}</FlagChip>
            {f.status === "resolved" ? <FlagChip tone="success">Resolved</FlagChip> : null}
            <span className="text-sm text-navy">{f.message}</span>
          </div>
          {f.working ? <p className="mt-1.5 text-xs text-muted-foreground">{f.working}</p> : null}
          {f.evidence.length > 0 ? (
            <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {f.evidence.map((e, j) => (
                <li key={j}>
                  {e.document_id ? (
                    <Link href={documentHref(pillarSlug, caseId, e.document_id)} className="underline underline-offset-2">
                      {e.label}
                    </Link>
                  ) : (
                    e.label
                  )}
                  {evidenceDetail(e) ? ` · ${evidenceDetail(e)}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
