import type { DocumentStatus } from "./types";

/** "pay_stub" -> "Pay stub". */
export function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * "5980.00" -> "5,980.00". Only adds thousands separators to the text the backend sent: no parsing
 * into a number, so nothing is rounded or changed (CLAUDE.md rule 1). Anything that is not a plain
 * amount is shown as it came, and a missing amount as a dash.
 */
export function formatMoney(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(amount);
  if (!match) return amount;
  const [, sign, whole, fraction = ""] = match;
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}

/**
 * A value read from a document, shown for a person. An amount with two decimals ("2760.00",
 * "-1200.50") gets thousands separators ("2,760.00"), the same as every other figure on screen.
 * Anything else is shown as it was read: a year, an account number, a name or a date has no
 * decimals and must not get commas. Text only; nothing is parsed into a number or rounded.
 */
export function formatFieldValue(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return /^-?\d+\.\d{2}$/.test(value) ? formatMoney(value) : value;
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
