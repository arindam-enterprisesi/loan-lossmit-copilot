import type { DocumentStatus } from "./types";

/** "pay_stub" -> "Pay stub". */
export function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const dateFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC", // fixed zone so server and browser render the same text
});

/** ISO date or date-time -> "2 Nov 2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dateFormat.format(new Date(iso));
}

export const DOC_STATUS_LABEL: Record<DocumentStatus, string> = {
  uploaded: "Uploaded",
  processing: "Processing",
  type_needed: "Type needed",
  needs_review: "Needs review",
  reviewed: "Reviewed",
  failed: "Failed",
};
