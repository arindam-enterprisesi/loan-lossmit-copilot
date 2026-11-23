import Link from "next/link";
import { documentHref, evidenceDetail } from "@/lib/income";
import type { EvidenceLink } from "@/lib/income-types";

/** Where a value came from: the document (linked when it has an ID), then its page and line. */
export function SourceLine({
  source,
  caseId,
  pillarSlug,
}: {
  source: EvidenceLink;
  caseId: string;
  pillarSlug: string;
}) {
  const detail = evidenceDetail(source);
  return (
    <span className="text-xs text-muted-foreground">
      {source.document_id ? (
        <Link href={documentHref(pillarSlug, caseId, source.document_id)} className="underline underline-offset-2">
          {source.label}
        </Link>
      ) : (
        source.label
      )}
      {detail ? ` · ${detail}` : ""}
    </span>
  );
}
