// Small display helpers for the Income analysis screen. No calculation: the backend returns every
// figure with its working, and these only turn that text into things to show or copy.
import type { WorkingEvidence } from "@/components/shared/show-working-drawer";
import type { EvidenceLink } from "./income-types";

/** The wording the brief requires under the candidate figure. */
export const CANDIDATE_LABEL = "candidate - qualifying income is determined by the underwriter";

/** The longest reason accepted when a component is included or excluded (same limit as other reasons). */
export const INCOME_REASON_MAX = 500;

/** "Page 2, line p2-L7" for an evidence link, or "" when it names no page or line. */
export function evidenceDetail(e: EvidenceLink): string {
  const parts: string[] = [];
  if (e.page) parts.push(`Page ${e.page}`);
  if (e.line_ids?.length) parts.push(`${e.line_ids.length > 1 ? "lines" : "line"} ${e.line_ids.join(", ")}`);
  return parts.join(", ");
}

/** The menu section where each pillar's documents live. */
export const DOCUMENT_SECTION: Record<string, string> = {
  underwriting: "document-intelligence",
  "loss-mitigation": "document-intake",
};

/** Where to read the whole document: its review screen, under that pillar's document section. */
export function documentHref(pillarSlug: string, caseId: string, documentId: string): string {
  const section = DOCUMENT_SECTION[pillarSlug] ?? "document-intelligence";
  return `/${pillarSlug}/${section}/${caseId}/${documentId}`;
}

/** Evidence links ready for the Show working drawer, linked to the document when it has an ID. */
export function workingEvidence(
  evidence: EvidenceLink[],
  pillarSlug: string,
  caseId: string,
): WorkingEvidence[] {
  const seen = new Set<string>();
  const items: WorkingEvidence[] = [];
  for (const e of evidence) {
    const item: WorkingEvidence = {
      label: e.label,
      detail: evidenceDetail(e) || undefined,
      href: e.document_id ? documentHref(pillarSlug, caseId, e.document_id) : undefined,
    };
    const key = `${item.label}|${item.detail ?? ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      items.push(item);
    }
  }
  return items;
}

/** The text that "Copy document requests" puts on the clipboard. */
export function requestsText(requests: string[]): string {
  if (requests.length === 0) return "";
  return ["Documents that would help settle the income flags:", ...requests.map((r) => `- ${r}`)].join("\n");
}
