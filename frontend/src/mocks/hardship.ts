// Mock hardship assessment for Angela Whitfield, shaped like the response proposed in
// src/lib/hardship-types.ts. The figures are the ones in data/synthetic/scenarios/angela_whitfield.json
// ("expected.hardship_profile", "expected.income", "expected.budget") and Feature Design 7.8:
// hours cut 40 to 30, pay 2,800.00 to 2,100.00 a half-month (25.00%), monthly income 4,200.00 gross and
// 3,350.00 net, expenses 3,420.00 stated against 3,630.00 observed, deficit 70.00 against 280.00,
// housing ratio 40.95% up from 30.71%, arrears 5,160.00, liquid assets 640.25 = 12.41% of arrears.
// The mock repeats those answers. It does not read the letter and it does not calculate ratios.
//
// What it does stand in for is the plain-code recalculation the backend does when a person adjusts a
// budget item (Feature Design 7.4: "adjusting the budget never calls the AI"): the difference, the
// flag, the totals and the surplus are worked out again, in whole cents so nothing is a float.
import { ApiError } from "@/lib/api-error";
import { AMOUNT_PATTERN, HARDSHIP_REASON_MAX, monthLabel, ONSET_HINT, ONSET_PATTERN } from "@/lib/hardship";
import type {
  Budget,
  BudgetAdjustmentRequest,
  BudgetLine,
  ConsistencyCheck,
  HardshipAssessment,
  Measure,
  ProfileConfirmation,
  ProfileItem,
  ProfileOption,
} from "@/lib/hardship-types";
import type { EvidenceLink } from "@/lib/income-types";
import { ANGELA_CASE_ID } from "./data";
import { formatCents, fromCents, toCents } from "./income";

const A = (n: number) => `d2000000-0000-4000-8000-00000000000${n}`;
const APPLICATION_ID = A(1);
const LETTER_ID = A(2);
const MORTGAGE_STATEMENT_ID = A(3);
const BANK_STATEMENT_ID = A(4);
const PAY_STUB_ID = A(5);

const ev = (label: string, document_id: string, line_ids?: string[]): EvidenceLink => ({
  label,
  document_id,
  page: 1,
  line_ids,
});

// Signed amounts: the money helpers in ./income only handle positive cents.
const sign = (cents: number) => (cents < 0 ? "-" : "");
const raw = (cents: number) => `${sign(cents)}${fromCents(Math.abs(cents))}`;
const fmt = (cents: number) => `${sign(cents)}${formatCents(Math.abs(cents))}`;

/** The hardship letter, line by line. Line IDs are p1-L1, p1-L2, ... as on every document page. */
const LETTER_TEXT = [
  "Angela Whitfield",
  "2210 Larkspur Court, Dayton, OH 45420",
  "Date: 2026-10-14",
  "Re: Loan 8800412271 - request for help with my mortgage",
  "Dear Loss Mitigation Team,",
  "Because my employer cut my hours from 40 to 30 a week in July, my pay fell by a quarter.",
  "I fell behind in August and I now owe 5,160.00 in missed payments.",
  "My take-home pay no longer covers my bills and the mortgage together.",
  "I do not know whether my hours will return to 40 a week.",
  "I have cut my spending where I can and I have used up my savings.",
  "I am enclosing my application, my recent pay stubs and my recent bank statements.",
  "I am asking for help to lower my payment so I can stay current.",
  "I have lived in this house for nine years and my family is here.",
  "I want to keep my home and I will do everything I can to make that work.",
  "Sincerely,",
  "Angela Whitfield",
];

/** The hardship categories from Feature Design 7.4. */
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

function profile(): ProfileItem[] {
  const quote = (text: string, line: number) => ({ text, line_ids: [`p1-L${line}`] });
  return [
    {
      key: "primary_reason",
      label: "Primary reason",
      value: "reduction_in_income",
      value_label: "Reduction in income",
      quote: quote("cut my hours from 40 to 30 a week in July", 6),
      quote_verified: true,
      options: REASON_OPTIONS,
      review: null,
    },
    {
      key: "onset",
      label: "Onset",
      value: "2026-07",
      value_label: "July 2026",
      quote: quote("in July", 6),
      quote_verified: true,
      options: null,
      review: null,
    },
    {
      key: "duration",
      label: "Duration",
      value: "unknown",
      value_label: "Unknown",
      quote: quote("I do not know whether my hours will return to 40 a week", 9),
      quote_verified: true,
      options: DURATION_OPTIONS,
      review: null,
    },
    {
      key: "intent",
      label: "Intent",
      value: "keep",
      value_label: "Keep the home",
      quote: quote("I want to keep my home", 14),
      quote_verified: true,
      options: INTENT_OPTIONS,
      review: null,
    },
  ];
}

// ---- Money, in whole cents --------------------------------------------------------------------
const NET_MONTHLY = toCents("3350.00");
const GROSS_MONTHLY = toCents("4200.00");
const GROSS_BEFORE = toCents("5600.00");
const HOUSING = toCents("1720.00");
const ARREARS = toCents("5160.00");
const LIQUID = toCents("640.25");

/** "A difference above 10% or 25.00, whichever is larger, is flagged" (Feature Design 7.4, illustrative). */
const tolerance = (stated: number) => Math.max(Math.round(Math.abs(stated) / 10), 2500);
const differs = (stated: number, observed: number) => Math.abs(observed - stated) > tolerance(stated);

const BANK = ev("Bank statement", BANK_STATEMENT_ID);
const APPLICATION = ev("Mortgage assistance application", APPLICATION_ID);

interface LineSeed {
  id: string;
  category: string;
  stated: string;
  observed: string;
  evidence: EvidenceLink[];
}

const LINE_SEEDS: LineSeed[] = [
  {
    id: "housing",
    category: "Housing (mortgage)",
    stated: "1720.00",
    observed: "1720.00",
    evidence: [ev("Mortgage statement", MORTGAGE_STATEMENT_ID), APPLICATION],
  },
  { id: "utilities", category: "Utilities", stated: "310.00", observed: "310.00", evidence: [BANK, APPLICATION] },
  { id: "food", category: "Food and everyday", stated: "780.00", observed: "780.00", evidence: [BANK, APPLICATION] },
  { id: "loans", category: "Loan payments", stated: "410.00", observed: "410.00", evidence: [BANK, APPLICATION] },
  { id: "other", category: "Other", stated: "200.00", observed: "410.00", evidence: [BANK, APPLICATION] },
];

/** The difference, the flag and its sentence for one line. Used for the first run and after every adjustment. */
function lineFrom(seed: Omit<BudgetLine, "difference" | "flagged" | "flag_message">): BudgetLine {
  const stated = toCents(seed.stated);
  const observed = toCents(seed.observed);
  const flagged = differs(stated, observed);
  return {
    ...seed,
    difference: raw(observed - stated),
    flagged,
    flag_message: flagged
      ? `Observed '${seed.category.toLowerCase()}' spending ${fmt(observed)} against ${fmt(stated)} stated — ask the borrower`
      : null,
  };
}

const OBSERVED_BASIS =
  "July 2026 statement (mortgage still being paid) and the mortgage statement; September carries the same non-housing totals";

function budgetFrom(lines: BudgetLine[]): Budget {
  const sum = (pick: (l: BudgetLine) => string) => lines.reduce((total, l) => total + toCents(pick(l)), 0);
  return {
    lines,
    stated_total: fromCents(sum((l) => l.stated)),
    observed_total: fromCents(sum((l) => l.observed)),
    observed_basis: OBSERVED_BASIS,
  };
}

/** Monthly surplus on both bases. The measure follows the budget, so it changes when an item is adjusted. */
function surplusMeasure(budget: Budget): Measure {
  const stated = NET_MONTHLY - toCents(budget.stated_total);
  const observed = NET_MONTHLY - toCents(budget.observed_total);
  const flagged = differs(stated, observed);
  const word = (c: number) => (c < 0 ? "deficit" : "surplus");
  return {
    id: "surplus",
    label: "Monthly surplus (observed)",
    value: raw(observed),
    unit: "money",
    compare: { label: "Stated", value: raw(stated), unit: "money" },
    note: null,
    flagged,
    flag_message: flagged
      ? `Observed ${word(observed)} ${formatCents(Math.abs(observed))} against ${formatCents(Math.abs(stated))} stated`
      : null,
    working: [
      {
        label: "Monthly surplus, stated basis",
        formula: `${formatCents(NET_MONTHLY)} − ${formatCents(toCents(budget.stated_total))}`,
        result: fmt(stated),
        note: "Net monthly income less the expenses on the application",
      },
      {
        label: "Monthly surplus, observed basis",
        formula: `${formatCents(NET_MONTHLY)} − ${formatCents(toCents(budget.observed_total))}`,
        result: fmt(observed),
        note: "Net monthly income less the expenses the documents show",
      },
    ],
    evidence: [ev("Pay stub", PAY_STUB_ID), BANK, APPLICATION],
  };
}

/** Expenses on both bases. Flagged when any line differs beyond the tolerance. */
function spendingCheck(budget: Budget): ConsistencyCheck {
  const flagged = budget.lines.find((l) => l.flagged);
  return {
    id: "spending",
    label: "Monthly expenses: application against documents",
    stated: { value: `${formatCents(toCents(budget.stated_total))} a month`, source: APPLICATION },
    documented: { value: `${formatCents(toCents(budget.observed_total))} a month`, source: BANK },
    status: flagged ? "flagged" : "consistent",
    detail: flagged?.flag_message ?? "Stated and observed spending agree within the tolerance.",
  };
}

const FIXED_CHECKS: ConsistencyCheck[] = [
  {
    id: "hours_vs_pay",
    label: "Hours cut against the change in pay",
    stated: {
      value: "Hours cut from 40 to 30 a week",
      source: ev("Hardship letter", LETTER_ID, ["p1-L6"]),
    },
    documented: {
      value: "Pay fell from 2,800.00 to 2,100.00 a half-month (25.00% lower)",
      source: ev("Pay stubs", PAY_STUB_ID),
    },
    status: "consistent",
    detail: "A cut from 40 to 30 hours is a quarter fewer hours, and pay fell by a quarter.",
  },
  {
    id: "reason",
    label: "Reason: letter against application",
    stated: { value: "Reduction in income", source: ev("Hardship letter", LETTER_ID, ["p1-L6"]) },
    documented: { value: "Reduction in income is ticked", source: APPLICATION },
    status: "consistent",
    detail: "The letter and the application give the same reason.",
  },
  {
    id: "intent",
    label: "Intent: letter against application",
    stated: { value: "Wants to keep the home", source: ev("Hardship letter", LETTER_ID, ["p1-L14"]) },
    documented: { value: "Keep the home", source: APPLICATION },
    status: "consistent",
    detail: "The letter and the application give the same intent.",
  },
  {
    id: "income",
    label: "Monthly gross income: application against pay stubs",
    stated: { value: "4,200.00 a month", source: APPLICATION },
    documented: { value: "4,200.00 a month (2,100.00 twice a month)", source: ev("Pay stubs", PAY_STUB_ID) },
    status: "consistent",
    detail: "The stated income matches the pay stubs.",
  },
  {
    id: "arrears",
    label: "Arrears: letter against mortgage statement",
    stated: { value: "5,160.00 in missed payments", source: ev("Hardship letter", LETTER_ID, ["p1-L7"]) },
    documented: { value: "5,160.00", source: ev("Mortgage statement", MORTGAGE_STATEMENT_ID) },
    status: "consistent",
    detail: "The amount in the letter matches the mortgage statement.",
  },
];

/** The measures that do not depend on the budget items: they come from the pay stubs, the loan and the application. */
const FIXED_MEASURES: Measure[] = [
  {
    id: "housing_ratio",
    label: "Housing ratio",
    value: "40.95",
    unit: "percent",
    compare: { label: "Before the cut", value: "30.71", unit: "percent" },
    note: "Mortgage payment as a share of gross monthly income",
    flagged: false,
    flag_message: null,
    working: [
      {
        label: "Housing ratio now",
        formula: `${formatCents(HOUSING)} ÷ ${formatCents(GROSS_MONTHLY)} × 100`,
        result: "40.95%",
        note: "Gross monthly income after the cut",
      },
      {
        label: "Housing ratio before the cut",
        formula: `${formatCents(HOUSING)} ÷ ${formatCents(GROSS_BEFORE)} × 100`,
        result: "30.71%",
        note: "Gross monthly income at 40 hours a week",
      },
    ],
    evidence: [ev("Mortgage statement", MORTGAGE_STATEMENT_ID), ev("Pay stubs", PAY_STUB_ID)],
  },
  {
    id: "arrears",
    label: "Arrears",
    value: "5160.00",
    unit: "money",
    compare: null,
    note: "Three monthly payments are unpaid",
    flagged: false,
    flag_message: null,
    working: [
      {
        label: "Arrears",
        formula: `3 × ${formatCents(HOUSING)}`,
        result: formatCents(ARREARS),
        note: "Missed payments, August to October",
      },
    ],
    evidence: [ev("Mortgage statement", MORTGAGE_STATEMENT_ID), ev("Hardship letter", LETTER_ID, ["p1-L7"])],
  },
  {
    id: "liquid_assets",
    label: "Liquid assets",
    value: "640.25",
    unit: "money",
    compare: null,
    note: "12.41% of arrears",
    flagged: false,
    flag_message: null,
    working: [
      {
        label: "Liquid assets as a share of arrears",
        formula: `${formatCents(LIQUID)} ÷ ${formatCents(ARREARS)} × 100`,
        result: "12.41%",
        note: "Checking account balance on the application",
      },
    ],
    evidence: [APPLICATION, BANK],
  },
  {
    id: "income_change",
    label: "Change in pay",
    value: "-25.00",
    unit: "percent",
    compare: null,
    note: "2,800.00 to 2,100.00 a half-month; 4,200.00 gross and 3,350.00 net a month",
    flagged: false,
    flag_message: null,
    working: [
      {
        label: "Change in pay per half-month",
        formula: "(2,100.00 − 2,800.00) ÷ 2,800.00 × 100",
        result: "-25.00%",
        note: "Pay stubs before and after the cut in hours",
      },
    ],
    evidence: [ev("Pay stubs", PAY_STUB_ID)],
  },
];

/** What the backend would return after a run for Angela. */
export function buildAngelaHardship(runAt: string, id = "ac000000-0000-4000-8000-000000000001"): HardshipAssessment {
  const budget = budgetFrom(LINE_SEEDS.map((s) => lineFrom({ ...s, adjustment: null })));
  return {
    id,
    case_id: ANGELA_CASE_ID,
    run_at: runAt,
    settings_label: "illustrative",
    letter: { document_id: LETTER_ID, lines: LETTER_TEXT.map((text, i) => ({ id: `p1-L${i + 1}`, text })) },
    profile: profile(),
    checks: [...FIXED_CHECKS, spendingCheck(budget)],
    budget,
    // Surplus first, then the measures from the brief, then the change in pay.
    measures: [surplusMeasure(budget), ...structuredClone(FIXED_MEASURES)],
  };
}

/** Which cases have a hardship letter to read. Only Angela's for now. */
export function hasHardshipSeed(caseId: string): boolean {
  return caseId === ANGELA_CASE_ID;
}

/**
 * PUT .../confirmations: records a specialist's decision on one profile item. A confirmation keeps
 * the value; a correction replaces it with a value from the allowed list (or a month, YYYY-MM, for
 * the onset) and needs a reason. What was originally read is kept in `review.original_label`.
 * Returns a new assessment, not a changed one.
 */
export function applyConfirmation(
  assessment: HardshipAssessment,
  confirmation: ProfileConfirmation,
  by: string,
  at: string,
): HardshipAssessment {
  const target = assessment.profile.find((p) => p.key === confirmation.key);
  if (!target) throw new ApiError(404, "Profile item not found");
  const original_label = target.review?.original_label ?? target.value_label;

  let next: ProfileItem;
  if (confirmation.action === "confirm") {
    next = { ...target, review: { status: "confirmed", reason: null, by, at, original_label } };
  } else if (confirmation.action === "correct") {
    const value = confirmation.value?.trim();
    const reason = confirmation.reason?.trim();
    if (!value) throw new ApiError(422, "A corrected value is required");
    if (!reason) throw new ApiError(422, "A reason is required");
    if (reason.length > HARDSHIP_REASON_MAX) {
      throw new ApiError(422, `The reason can be at most ${HARDSHIP_REASON_MAX} characters`);
    }
    const option = target.options?.find((o) => o.value === value);
    if (target.options && !option) throw new ApiError(422, "Choose one of the listed values");
    // The onset is a month, written the way the backend stores it.
    if (target.key === "onset" && !ONSET_PATTERN.test(value)) throw new ApiError(422, ONSET_HINT);
    next = {
      ...target,
      value,
      value_label: option?.label ?? (target.key === "onset" ? monthLabel(value) : value),
      review: { status: "corrected", reason, by, at, original_label },
    };
  } else {
    throw new ApiError(422, "Unknown action");
  }
  return { ...assessment, profile: assessment.profile.map((p) => (p.key === next.key ? next : p)) };
}

/**
 * PATCH .../budget-items/{item}: a person sets how much of an expense counts each month (for example
 * a one-off spend). The observed amount it replaced is kept; the differences, flags, totals, the
 * surplus and the expenses check are worked out again. Returns a new assessment, not a changed one.
 */
export function applyBudgetAdjustment(
  assessment: HardshipAssessment,
  itemId: string,
  request: BudgetAdjustmentRequest,
  by: string,
  at: string,
): HardshipAssessment {
  const reason = request.reason?.trim();
  if (!reason) throw new ApiError(422, "A reason is required");
  if (reason.length > HARDSHIP_REASON_MAX) {
    throw new ApiError(422, `The reason can be at most ${HARDSHIP_REASON_MAX} characters`);
  }
  const amount = request.amount?.trim();
  if (!amount || !AMOUNT_PATTERN.test(amount)) throw new ApiError(422, "Enter an amount such as 200.00");
  const target = assessment.budget.lines.find((l) => l.id === itemId);
  if (!target) throw new ApiError(404, "Budget item not found");

  const lines = assessment.budget.lines.map((l) =>
    l.id === itemId
      ? lineFrom({
          ...l,
          observed: fromCents(toCents(amount)),
          // The first observed amount is the one to keep, even after several adjustments.
          adjustment: { original_observed: l.adjustment?.original_observed ?? l.observed, reason, by, at },
        })
      : l,
  );
  const budget = budgetFrom(lines);
  return {
    ...assessment,
    budget,
    checks: assessment.checks.map((c) => (c.id === "spending" ? spendingCheck(budget) : c)),
    measures: assessment.measures.map((m) => (m.id === "surplus" ? surplusMeasure(budget) : m)),
  };
}
