// Small display helpers for the Hardship and budget screen. No calculation: the backend returns
// every figure with its working, and these only turn that text into things to show.
import { formatMoney } from "./format";
import type { MeasureUnit, ProfileItem } from "./hardship-types";

/** The longest reason accepted when a profile item or a budget item is changed. */
export const HARDSHIP_REASON_MAX = 500;

/** A money amount as the backend writes it: digits with up to two decimals ("200", "200.5", "200.00"). */
export const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/;

/** A month as the backend stores the onset: "2026-07". */
export const ONSET_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;
export const ONSET_HINT = "Write the month as YYYY-MM, for example 2026-07";

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** "2026-07" -> "July 2026". Anything that is not a month is shown as it came. */
export function monthLabel(value: string): string {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(value);
  return match ? `${MONTH_NAMES[Number(match[2]) - 1]} ${match[1]}` : value;
}

/** What follows a figure on the screen: nothing for money, a percent sign for a ratio. */
export const MEASURE_UNIT_SUFFIX: Record<MeasureUnit, string> = { money: "", percent: "%" };

/** "-280.00" -> "-280.00"; "5160.00" -> "5,160.00"; a ratio gets its sign: "40.95" -> "40.95%". */
export function measureText(value: string, unit: MeasureUnit): string {
  return `${formatMoney(value)}${MEASURE_UNIT_SUFFIX[unit]}`;
}

/** "210.00" -> "+210.00"; "-5.00" stays; "0.00" stays. Only adds a sign to the backend's text. */
export function signedMoney(difference: string): string {
  const shown = formatMoney(difference);
  const isPositive = /^\d/.test(difference) && !/^0(\.0+)?$/.test(difference);
  return isPositive ? `+${shown}` : shown;
}

/** One piece of a letter line: plain text, or text that is (part of) a quote for a profile item. */
export interface LineSegment {
  text: string;
  /** The profile item whose quote this is, or null for plain text. */
  key: ProfileItem["key"] | null;
}

/**
 * Splits one letter line so each quote that cites it can be highlighted. A quote is an exact piece of
 * its cited lines, so it is found by text. If a quote spans several lines (not found whole in this
 * one), the whole line is highlighted. Overlapping quotes: the earlier one wins the overlap.
 */
export function splitLine(lineId: string, text: string, items: ProfileItem[]): LineSegment[] {
  const cited = items.filter((i) => i.quote?.line_ids.includes(lineId));
  if (cited.length === 0) return [{ text, key: null }];

  const spans: { start: number; end: number; key: ProfileItem["key"] }[] = [];
  for (const item of cited) {
    const quote = item.quote!.text;
    const start = quote ? text.indexOf(quote) : -1;
    if (start >= 0) spans.push({ start, end: start + quote.length, key: item.key });
    else return [{ text, key: item.key }]; // the quote runs over several lines
  }
  spans.sort((a, b) => a.start - b.start);

  const out: LineSegment[] = [];
  let at = 0;
  for (const s of spans) {
    if (s.start < at) continue; // overlaps a quote already shown
    if (s.start > at) out.push({ text: text.slice(at, s.start), key: null });
    out.push({ text: text.slice(s.start, s.end), key: s.key });
    at = s.end;
  }
  if (at < text.length) out.push({ text: text.slice(at), key: null });
  return out;
}

/** The text of a profile item's value while a review is pending, or after it. */
export function reviewLabel(item: ProfileItem): string {
  if (!item.review) return "Not reviewed";
  return item.review.status === "confirmed" ? "Reviewer-confirmed" : "Reviewer-corrected";
}
