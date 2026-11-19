import { humanize } from "./format";
import type { Certainty, DocumentType, Field, ReviewStatus } from "./types";
import type { ChipTone } from "@/components/shared/flag-chip";

/** Types a user can pick. "unrecognized" is something the system assigns, never a choice. */
export const DOCUMENT_TYPES: DocumentType[] = [
  "pay_stub",
  "bank_statement",
  "tax_return_1040",
  "w2",
  "credit_report",
  "mortgage_assistance_application",
  "mortgage_statement",
  "benefits_letter",
  "expense_bill",
  "hardship_letter",
];

const TYPE_LABEL_OVERRIDES: Partial<Record<DocumentType, string>> = {
  tax_return_1040: "Tax return (1040)",
  w2: "W-2",
};

export function docTypeLabel(type: DocumentType | null | undefined): string {
  if (!type) return "Not set";
  return TYPE_LABEL_OVERRIDES[type] ?? humanize(type);
}

export const ACCEPTED_MIME = ["application/pdf", "image/png", "image/jpeg"] as const;

export interface FileCheck {
  accepted: File[];
  rejected: { name: string; reason: string }[];
}

/** The contract accepts PDF, PNG or JPEG only (anything else is a 415). Catch it before uploading. */
export function checkFiles(files: File[]): FileCheck {
  const accepted: File[] = [];
  const rejected: FileCheck["rejected"] = [];
  for (const f of files) {
    if ((ACCEPTED_MIME as readonly string[]).includes(f.type)) accepted.push(f);
    else rejected.push({ name: f.name, reason: "Only PDF, PNG or JPEG files can be uploaded." });
  }
  return { accepted, rejected };
}

/** "net_pay_current" -> "Net pay current". */
export function fieldLabel(name: string): string {
  return humanize(name);
}

/** A field still needs a person when it carries flags and nobody has reviewed it yet. */
export function hasOpenFlags(field: Field): boolean {
  return field.flags.length > 0 && field.review_status === "unreviewed";
}

/** Fields with open flags first; otherwise keeps the order the API returned. */
export function sortFlaggedFirst(fields: Field[]): Field[] {
  return [...fields].sort((a, b) => Number(hasOpenFlags(b)) - Number(hasOpenFlags(a)));
}

export function certaintyTone(c: Certainty): ChipTone {
  return c === "high" ? "success" : c === "medium" ? "warning" : "danger";
}

export const CERTAINTY_LABEL: Record<Certainty, string> = {
  high: "High certainty",
  medium: "Medium certainty",
  low: "Low certainty",
};

export const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  unreviewed: "Not reviewed",
  confirmed: "Confirmed",
  corrected: "Corrected",
  rejected: "Rejected",
};

export const REVIEW_STATUS_TONE: Record<ReviewStatus, ChipTone> = {
  unreviewed: "neutral",
  confirmed: "success",
  corrected: "info",
  rejected: "danger",
};
