// Reads the real backend's hardship answers into the shapes the Hardship and budget screen uses.
//
// The real shapes are in backend/app/api/schemas/hardship.py (on `main` since PR #12, 23 Nov 2026). They
// are not in contracts/openapi.yaml. This file only translates:
// it renames fields, picks display labels and cuts the backend's own working text into steps. It never
// calculates (CLAUDE.md rule 1). A percentage comes from the end of the backend's working text
// ("... = 40.95%"), because the backend sends ratios as six-place decimals ("0.409524").
//
// If the backend's shapes change, this is the only file that changes.
import { evidenceOf, percentFromWorking, shownValue, stepOf, type RealCalc, type RealRef } from "./calc-real";
import { humanize } from "./format";
import { monthLabel } from "./hardship";
import type {
  Budget,
  BudgetAdjustmentRequest,
  BudgetLine,
  ConsistencyCheck,
  HardshipAssessment,
  HardshipLetter,
  Measure,
  ProfileConfirmation,
  ProfileItem,
  ProfileKey,
  ProfileOption,
} from "./hardship-types";

export type { RealCalc, RealRef } from "./calc-real";

// --- what the backend sends ----------------------------------------------------------------

interface RealQuoted {
  quote: string | null;
  lines: string[];
  verified: boolean;
  check_flags: string[];
}

interface RealConfirmation {
  status: "confirmed" | "corrected";
  value: string;
  original: string | null;
  reason: string | null;
  /** The reviewer's user id. The backend does not send a name yet. */
  by: string;
  at: string;
  label: string;
}

interface RealWithConfirmation {
  confirmation?: RealConfirmation | null;
}

export interface RealBudgetLine {
  id: string;
  category: string;
  stated: string | null;
  observed: string | null;
  observed_month: string | null;
  adjusted: string | null;
  adjustment_reason: string | null;
  effective_observed: string | null;
  /** Stated against what counts, always positive. */
  difference: string | null;
  flagged: boolean;
  change: { reason: string; by: string; at: string } | null;
  stated_calc: RealCalc | null;
  observed_calc: RealCalc | null;
}

export interface RealCheck {
  name: string;
  agrees: boolean;
  working: string;
  values: Record<string, string>;
}

export interface RealFlag {
  id: string;
  code: string;
  severity: string;
  message: string;
  status: string;
  working: string | null;
  refs: RealRef[];
}

export interface RealHardshipAssessment {
  run_id: string;
  source: "model" | "seeded_sample";
  created_at: string;
  letter_document_id: string | null;
  config_version: string;
  config_label: "illustrative" | "authoritative";
  profile: {
    primary_reason: RealQuoted &
      RealWithConfirmation & { category: string; category_label: string; sensitive: boolean; financial_effect: string };
    onset: RealQuoted & RealWithConfirmation & { as_stated: string | null; month: string | null };
    duration: RealQuoted & RealWithConfirmation & { category: "temporary" | "long_term" | "unknown" };
    intent: RealQuoted & RealWithConfirmation & { category: "keep" | "sell" | "unsure" };
  };
  budget: RealBudgetLine[];
  measures: RealCalc[];
  checks: RealCheck[];
  budget_flags: RealFlag[];
  budget_note: string | null;
}

// --- the lists a correction chooses from ------------------------------------------------------
// The backend checks a correction against its own list (backend/config/hardship.yaml for the reasons).
// It does not send the list yet, so it is repeated here. Ask the backend to send it instead.

const REASON_OPTIONS: ProfileOption[] = [
  { value: "reduction_in_income", label: "Reduction in income" },
  { value: "unemployment", label: "Unemployment" },
  { value: "increase_in_housing_expense", label: "Increase in housing expense" },
  { value: "medical_or_disability", label: "Medical or disability" },
  { value: "divorce_or_separation", label: "Divorce or separation" },
  { value: "death_in_household", label: "Death in household" },
  { value: "disaster", label: "Disaster" },
  { value: "business_failure", label: "Business failure" },
  { value: "other", label: "Other" },
];
const DURATION_OPTIONS: ProfileOption[] = [
  { value: "temporary", label: "Temporary" },
  { value: "long_term", label: "Long-term" },
  { value: "unknown", label: "Unknown" },
];
const INTENT_OPTIONS: ProfileOption[] = [
  { value: "keep", label: "Keep the home" },
  { value: "sell", label: "Sell" },
  { value: "unsure", label: "Unsure" },
];

const labelOf = (options: ProfileOption[] | null, value: string): string =>
  options?.find((o) => o.value === value)?.label ?? monthLabel(value);

// --- the profile ----------------------------------------------------------------------------

function profileItem(
  key: ProfileKey,
  label: string,
  read: { value: string; label?: string },
  quoted: RealQuoted & RealWithConfirmation,
  options: ProfileOption[] | null,
): ProfileItem {
  const confirmation = quoted.confirmation ?? null;
  const readLabel = read.label ?? labelOf(options, read.value);
  return {
    key,
    label,
    value: confirmation?.value ?? read.value,
    value_label: confirmation ? labelOf(options, confirmation.value) : readLabel,
    quote: quoted.quote ? { text: quoted.quote, line_ids: quoted.lines } : null,
    quote_verified: quoted.verified,
    options,
    review: confirmation
      ? {
          status: confirmation.status,
          reason: confirmation.reason,
          by: confirmation.by,
          at: confirmation.at,
          original_label: confirmation.original ? labelOf(options, confirmation.original) : readLabel,
        }
      : null,
  };
}

function profileFrom(real: RealHardshipAssessment): ProfileItem[] {
  const p = real.profile;
  return [
    profileItem(
      "primary_reason",
      "Primary reason",
      { value: p.primary_reason.category, label: p.primary_reason.category_label },
      p.primary_reason,
      REASON_OPTIONS,
    ),
    profileItem(
      "onset",
      "Onset",
      {
        value: p.onset.month ?? p.onset.as_stated ?? "",
        label: p.onset.month ? monthLabel(p.onset.month) : (p.onset.as_stated ?? "Not stated"),
      },
      p.onset,
      null,
    ),
    profileItem("duration", "Duration", { value: p.duration.category }, p.duration, DURATION_OPTIONS),
    profileItem("intent", "Intent", { value: p.intent.category }, p.intent, INTENT_OPTIONS),
  ];
}

// --- the letter -----------------------------------------------------------------------------

const lineOrder = (id: string): [number, number] => {
  const m = /^p(\d+)-L(\d+)$/.exec(id);
  return m ? [Number(m[1]), Number(m[2])] : [Number.MAX_SAFE_INTEGER, 0];
};

/**
 * The backend does not return the letter's text yet, only each quote and the line IDs it sits on. So
 * the letter shown is the quoted lines. A quote that runs over several lines is shown on its first
 * line, and the rest show an ellipsis. `partial` makes the screen say so.
 */
function letterFrom(items: ProfileItem[], documentId: string | null): HardshipLetter {
  const texts = new Map<string, string>();
  for (const item of items) {
    const quote = item.quote;
    if (!quote) continue;
    quote.line_ids.forEach((id, i) => {
      const text = i === 0 ? quote.text : "…";
      const existing = texts.get(id);
      if (existing === undefined) texts.set(id, text);
      else if (text !== "…" && !existing.includes(text)) texts.set(id, `${existing} … ${text}`);
    });
  }
  const lines = [...texts.entries()]
    .map(([id, text]) => ({ id, text }))
    .sort((a, b) => {
      const [pa, la] = lineOrder(a.id);
      const [pb, lb] = lineOrder(b.id);
      return pa - pb || la - lb;
    });
  return { document_id: documentId ?? "", lines, partial: true };
}

// --- evidence and working -------------------------------------------------------------------

// --- the measures ---------------------------------------------------------------------------

interface MeasureSpec {
  id: string;
  name: string;
  label: string;
  compare?: { name: string; label: string };
  /** A second calculation whose percentage becomes the note, e.g. "12.41% of arrears". */
  note?: { name: string; suffix: string };
}

const MEASURES: MeasureSpec[] = [
  { id: "surplus", name: "surplus_observed", label: "Monthly surplus (observed)", compare: { name: "surplus_stated", label: "Stated" } },
  { id: "housing_ratio", name: "housing_ratio", label: "Housing ratio", compare: { name: "housing_ratio_before_cut", label: "Before the cut" } },
  { id: "arrears", name: "arrears", label: "Arrears" },
  { id: "liquid_assets", name: "liquid_assets", label: "Liquid assets", note: { name: "liquid_assets_share_of_arrears", suffix: "of arrears" } },
  { id: "income_change", name: "income_change", label: "Change in pay" },
];

function measuresFrom(calcs: RealCalc[]): Measure[] {
  const byName = new Map(calcs.map((c) => [c.name, c]));
  const out: Measure[] = [];
  for (const spec of MEASURES) {
    const calc = byName.get(spec.name);
    if (!calc) continue;
    const shown = shownValue(calc);
    const other = spec.compare ? byName.get(spec.compare.name) : undefined;
    const otherShown = other ? shownValue(other) : null;
    const noteCalc = spec.note ? byName.get(spec.note.name) : undefined;
    const notePercent = noteCalc ? percentFromWorking(noteCalc.working) : null;
    out.push({
      id: spec.id,
      label: spec.label,
      value: shown.value,
      unit: shown.unit,
      compare:
        other && otherShown && spec.compare
          ? { label: spec.compare.label, value: otherShown.value, unit: otherShown.unit }
          : null,
      note: notePercent && spec.note ? `${notePercent}% ${spec.note.suffix}` : null,
      // The backend does not flag measures. It flags budget lines and checks.
      flagged: false,
      flag_message: null,
      working: [stepOf(calc), ...(other ? [stepOf(other)] : []), ...(noteCalc ? [stepOf(noteCalc)] : [])],
      evidence: evidenceOf([...calc.evidence, ...(other?.evidence ?? [])]),
    });
  }
  return out;
}

// --- the budget -----------------------------------------------------------------------------

function budgetFrom(real: RealHardshipAssessment): Budget {
  const byName = new Map(real.measures.map((c) => [c.name, c]));
  const lineFlags = real.budget_flags.filter((f) => f.code === "HB-W101");
  const lines: BudgetLine[] = real.budget.map((l) => {
    const category = humanize(l.category);
    return {
      id: l.id,
      category,
      stated: l.stated ?? "",
      observed: l.effective_observed ?? l.observed ?? "",
      difference: l.difference ?? "",
      difference_unsigned: true,
      flagged: l.flagged,
      flag_message: lineFlags.find((f) => f.message.toLowerCase().includes(l.category.toLowerCase()))?.message ?? null,
      adjustment:
        l.adjusted !== null
          ? {
              original_observed: l.observed ?? "",
              reason: l.adjustment_reason ?? l.change?.reason ?? "",
              by: l.change?.by ?? "",
              at: l.change?.at ?? "",
            }
          : null,
      evidence: evidenceOf([...(l.stated_calc?.evidence ?? []), ...(l.observed_calc?.evidence ?? [])]),
    };
  });
  const months = [...new Set(real.budget.map((l) => l.observed_month).filter((m): m is string => !!m))];
  return {
    lines,
    stated_total: byName.get("stated_expenses_total")?.value ?? "",
    observed_total: byName.get("observed_expenses_total")?.value ?? "",
    observed_basis: months.length
      ? `Observed basis: the ${months.join(" and ")} statement (the latest month with a debit in each line)`
      : "Observed basis: not stated by the backend",
  };
}

// --- the consistency checks -----------------------------------------------------------------

const CHECK_LABELS: Record<string, string> = {
  check_income_stated_vs_documented: "Income: stated and documented",
  check_pay_vs_hours: "Hours cut against the change in pay",
  check_reason_vs_letter: "Reason: application and letter",
  check_intent_vs_letter: "Intent: application and letter",
};

const INTENT_TEXT: Record<string, string> = { keep: "Keep the home", sell: "Sell", unsure: "Unsure" };

function checkFrom(c: RealCheck): ConsistencyCheck {
  const v = c.values;
  let stated: ConsistencyCheck["stated"];
  let documented: ConsistencyCheck["documented"];
  if (c.name === "check_income_stated_vs_documented") {
    stated = { value: v.stated ?? "—", source: { label: "Application" } };
    documented = { value: v.documented ?? "—", source: { label: "Pay stubs" } };
  } else if (c.name === "check_pay_vs_hours") {
    // The backend's sentence carries both percentages already formatted; the raw values are ratios.
    const pay = /changed by (-?\d[\d.]*%)/.exec(c.working)?.[1];
    const hours = /hours changed by (-?\d[\d.]*%) \(([^)]*)\)/.exec(c.working);
    stated = {
      value: hours ? `Hours changed by ${hours[1]} (${hours[2]})` : (v.hours_change ?? "—"),
      source: { label: "Hardship letter" },
    };
    documented = { value: pay ? `Pay changed by ${pay}` : (v.pay_change ?? "—"), source: { label: "Pay stubs" } };
  } else if (c.name === "check_intent_vs_letter") {
    stated = { value: INTENT_TEXT[v.application] ?? v.application ?? "—", source: { label: "Application" } };
    documented = { value: INTENT_TEXT[v.letter] ?? v.letter ?? "—", source: { label: "Hardship letter" } };
  } else {
    stated = { value: v.application ?? "—", source: { label: "Application" } };
    documented = { value: v.letter ?? "—", source: { label: "Hardship letter" } };
  }
  return {
    id: c.name,
    label: CHECK_LABELS[c.name] ?? humanize(c.name.replace(/^check_/, "")),
    stated,
    documented,
    status: c.agrees ? "consistent" : "flagged",
    detail: c.working,
  };
}

// --- the whole assessment -------------------------------------------------------------------

export function toHardshipAssessment(real: RealHardshipAssessment, caseId: string): HardshipAssessment {
  const profile = profileFrom(real);
  return {
    id: real.run_id,
    case_id: caseId,
    run_at: real.created_at,
    settings_label: real.config_label,
    letter: letterFrom(profile, real.letter_document_id),
    profile,
    checks: real.checks.map(checkFrom),
    budget: budgetFrom(real),
    measures: measuresFrom(real.measures),
    budget_note: real.budget_note,
  };
}

// --- what a person sends --------------------------------------------------------------------

/** PUT .../latest/confirmations names the item: `{ duration: { value, reason } }`, or `{ duration: {} }` to confirm. */
export function confirmationRequest(c: ProfileConfirmation): Partial<Record<ProfileKey, { value?: string; reason?: string }>> {
  if (c.action === "confirm") return { [c.key]: {} };
  return { [c.key]: { value: c.value, reason: c.reason } };
}

/** PATCH .../latest/budget/{line_id}: the amount stays text, so nothing is rounded on the way. Null clears an adjustment. */
export function adjustmentRequest(a: BudgetAdjustmentRequest): { adjusted_amount: string | null; reason: string } {
  return { adjusted_amount: a.amount, reason: a.reason };
}
