import Link from "next/link";
import type { EvidenceRef } from "@/lib/copilot-types";
import { evidenceLink } from "@/lib/copilot";

interface EvidenceLinksProps {
  refs: EvidenceRef[];
  caseId: string;
  pillarSlug: string;
  /** Opens a cited guideline passage. A passage reference is plain text without it. */
  onOpenPassage?: (passageId: string) => void;
}

/**
 * Where a finding, a conflict or a condition came from: the calculation, rule, checklist item, document or
 * passage, each linked to the screen that shows it. A reference no screen shows is plain text.
 */
export function EvidenceLinks({ refs, caseId, pillarSlug, onOpenPassage }: EvidenceLinksProps) {
  if (refs.length === 0) return null;
  return (
    <ul aria-label="Evidence" className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {refs.map((ref, i) => {
        const link = evidenceLink(ref, pillarSlug, caseId);
        const lines = ref.line_ids?.length ? ` · ${ref.line_ids.length > 1 ? "lines" : "line"} ${ref.line_ids.join(", ")}` : "";
        return (
          <li key={`${ref.kind}-${ref.id}-${i}`}>
            {ref.kind === "passage" && onOpenPassage ? (
              <button type="button" className="underline underline-offset-2" onClick={() => onOpenPassage(ref.id)}>
                {link.label}
              </button>
            ) : link.href ? (
              <Link href={link.href} className="underline underline-offset-2">
                {link.label}
              </Link>
            ) : (
              link.label
            )}
            {lines}
          </li>
        );
      })}
    </ul>
  );
}
