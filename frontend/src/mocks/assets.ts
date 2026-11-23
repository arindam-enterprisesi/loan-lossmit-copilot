// Mock asset and liability analysis for Daniel Reyes, shaped like the screen's own types
// (src/lib/assets-types.ts). The figures are the ones in data/synthetic/scenarios/daniel_reyes.json
// ("expected.assets_liabilities") and Feature Design 3.8: documented assets 9,226.32 against 36,500.00
// needed, obligations 693.00 a month, front-end ratio 33.11%, DTI 44.70% (above the illustrative 43%
// level), LTV 90.00%, and DTI 41.61% if overtime were counted. The transactions are the 30 lines of his
// September statement with the categories the scenario gives.
//
// The mock stands in for the backend, so it does what the backend does after a change: it adds the
// counted obligations and works the three ratios out again, in whole cents (plain code, no AI, Feature
// Design 3.4 step 9). The screen itself never calculates.
import type { WorkingStep } from "@/components/shared/show-working-drawer";
import { ApiError } from "@/lib/api-error";
import {
  ASSET_REASON_MAX,
  TRANSACTION_CATEGORIES,
  validateScenario,
} from "@/lib/assets";
import type {
  AssetAnalysis,
  AssetFigure,
  AssetFlag,
  AssetObligation,
  AssetTransaction,
  FigureUnit,
  LoanScenario,
  LoanScenarioInput,
  ObligationReview,
  OtherFigure,
  TransactionCategory,
  TransactionReview,
} from "@/lib/assets-types";
import type { EvidenceLink } from "@/lib/income-types";
import { DANIEL_CASE_ID } from "./data";
import { BANK_DOC_DANIEL_ID } from "./extraction";
import { formatCents, fromCents, toCents } from "./income";

/** What a run read: the loan scenario, and the candidate income from the income analysis. */
export interface AssetRun {
  scenario: LoanScenarioInput;
  /** Candidate monthly income, e.g. "5980.00". */
  candidate_monthly: string;
  /** Overtime a month when the income analysis left it out, else null: the "what if" is built from it. */
  overtime_monthly: string | null;
}

/** Which cases have bank statements to analyse. Only Daniel's for now. */
export const hasAssetSeed = (caseId: string): boolean => caseId === DANIEL_CASE_ID;

/** The sample loan from daniel_reyes.json, as if the demo seed had entered it. */
export const DANIEL_SCENARIO: LoanScenarioInput = {
  purpose: "purchase",
  occupancy: "primary residence",
  property_value: "400000.00",
  loan_amount: "360000.00",
  proposed_housing_payment: "1980.00",
  funds_to_close: "36500.00",
};

/** Used when the income analysis has not been run: the figures in the scenario file. */
export const DEFAULT_CANDIDATE = "5980.00";
export const DEFAULT_OVERTIME = "444.41";

const CLOSING_BALANCE = "9226.32"; // account ending 6032, closing balance on 30 Sep 2026
const ACCOUNT = "6032";
const LARGE_DEPOSIT_FROM = 100000; // 1,000.00 in cents (Feature Design 3.3)
const REVIEW_LEVEL = 4300; // 43.00%, the illustrative DTI review level, in hundredths of a percent
const NOTE = "Candidate figures for the underwriter to review. They are not a decision.";

// ---- The September statement, as the model labelled it -----------------------------------------

const ROWS: [string, string, string, TransactionCategory, string][] = [
  ["2026-09-01", "OAKMONT APARTMENTS RENT", "-1425.00", "housing payment", "Oakmont Apartments"],
  ["2026-09-04", "CEDAR VALLEY MFG PAYROLL", "2033.61", "payroll deposit", "Cedar Valley Manufacturing"],
  ["2026-09-04", "MARATHON PETRO 4410", "-37.86", "everyday spending", "Marathon"],
  ["2026-09-05", "LAKESHORE AUTO FINANCE", "-420.00", "loan payment", "Lakeshore Auto Finance"],
  ["2026-09-05", "MARATHON PETRO 4410", "-17.99", "everyday spending", "Marathon"],
  ["2026-09-06", "MARATHON PETRO 4410", "-52.38", "everyday spending", "Marathon"],
  ["2026-09-06", "TARGET T-1124", "-29.67", "other", "Target"],
  ["2026-09-09", "BUCKEYE POWER & GAS", "-96.40", "utility", "Buckeye Power & Gas"],
  ["2026-09-10", "BRIGHTPATH STUDENT LOAN", "-110.00", "loan payment", "Brightpath Student Loan Servicing"],
  ["2026-09-10", "MARATHON PETRO 4410", "-47.14", "everyday spending", "Marathon"],
  ["2026-09-10", "ALDI 55021", "-49.22", "everyday spending", "Aldi"],
  ["2026-09-12", "NORTHGATE CARD PAYMENT", "-88.00", "credit card payment", "Northgate Card"],
  ["2026-09-13", "KROGER #0412", "-70.26", "everyday spending", "Kroger"],
  ["2026-09-13", "HOME DEPOT 3871", "-48.86", "other", "Home Depot"],
  ["2026-09-14", "CARDINAL REWARDS VISA PMT", "-40.00", "credit card payment", "Cardinal Rewards Visa"],
  ["2026-09-16", "SKYLINE FIBER INTERNET", "-79.99", "utility", "Skyline Fiber"],
  ["2026-09-16", "KROGER #0412", "-63.27", "everyday spending", "Kroger"],
  ["2026-09-16", "MARATHON PETRO 4410", "-49.47", "everyday spending", "Marathon"],
  ["2026-09-17", "SHELL OIL 574412", "-70.47", "everyday spending", "Shell"],
  ["2026-09-18", "CEDAR VALLEY MFG PAYROLL", "2033.61", "payroll deposit", "Cedar Valley Manufacturing"],
  ["2026-09-18", "STATELINE WIRELESS", "-65.00", "utility", "Stateline Wireless"],
  ["2026-09-18", "PANERA BREAD 4471", "-90.19", "everyday spending", "Panera"],
  ["2026-09-20", "TRILLIUM AUTO INSURANCE", "-112.50", "insurance", "Trillium Insurance"],
  ["2026-09-20", "TARGET T-1124", "-40.36", "other", "Target"],
  ["2026-09-22", "ZELLE FROM PATRICIA OWENS REF 8841", "2000.00", "transfer in", "Patricia Owens"],
  ["2026-09-22", "LOCAL TAP HOUSE", "-23.95", "everyday spending", "Local Tap House"],
  ["2026-09-22", "KROGER #0412", "-15.77", "everyday spending", "Kroger"],
  ["2026-09-23", "SPEEDWAY 08821", "-71.93", "everyday spending", "Speedway"],
  ["2026-09-24", "PANERA BREAD 4471", "-62.05", "everyday spending", "Panera"],
  ["2026-09-24", "AMAZON MKTPLACE", "-18.30", "other", "Amazon"],
];

/** The line a row sits on: twelve rows on page 1 (from line 8), then twelve on page 2, then the rest. */
function lineId(i: number): string {
  if (i < 12) return `p1-L${8 + i}`;
  if (i < 24) return `p2-L${4 + (i - 12)}`;
  return `p3-L${4 + (i - 24)}`;
}

const txId = (i: number) => `a1000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`;
const obId = (i: number) => `a2000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`;

const bankLine = (i: number): EvidenceLink => ({
  label: "Bank statement, Sep 2026, account ending 6032",
  document_id: BANK_DOC_DANIEL_ID,
  line_ids: [lineId(i)],
});

function baseTransactions(): AssetTransaction[] {
  return ROWS.map(([posted_on, description, amount, category, counterparty], i) => {
    const credit = !amount.startsWith("-");
    return {
      id: txId(i),
      document_id: BANK_DOC_DANIEL_ID,
      line_id: lineId(i),
      account_last4: ACCOUNT,
      posted_on,
      description,
      amount,
      direction: credit ? "credit" : "debit",
      category,
      category_source: "ai",
      system_category: category,
      counterparty,
      needs_review: false,
      sourced: false,
      sourced_note: null,
      change: null,
      payroll_match:
        category === "payroll deposit" ? `Net pay ${formatCents(toCents(amount))} matches the pay stub, pay date ${posted_on}` : null,
      flags: [],
    };
  });
}

export function baseObligations(): AssetObligation[] {
  const row = (
    i: number,
    creditor: string,
    kind: string,
    payment: string,
    balance: string | null,
    source: AssetObligation["source"],
    counts: boolean,
    reason: string,
  ): AssetObligation => ({
    id: obId(i),
    creditor,
    kind,
    monthly_payment: payment,
    balance,
    source,
    counts_toward_dti: counts,
    system_counts_toward_dti: counts,
    reason,
    change: null,
  });
  const BOTH = "On the credit report and in the bank statements.";
  const CREDIT = "Credit report liability with a monthly payment above zero.";
  return [
    row(0, "Northgate Card", "credit card", "88.00", "2940.00", "both", true, BOTH),
    row(1, "Cardinal Rewards Visa", "credit card", "40.00", "1240.00", "both", true, BOTH),
    row(2, "Harbor Retail Card", "credit card", "35.00", "300.00", "credit_report", true, CREDIT),
    row(3, "Lakeshore Auto Finance", "auto loan", "420.00", "14860.00", "both", true, BOTH),
    row(4, "Brightpath Student Loan Servicing", "student loan", "110.00", "18430.00", "both", true, BOTH),
    row(5, "Oakmont Apartments", "rent", "1425.00", null, "bank", false, "Current rent on a purchase of a primary residence."),
  ];
}

// ---- Whole-cent arithmetic, standing in for the backend's calculation service -------------------

/** A ratio as a percentage text with two decimals: 198000 over 598000 is "33.11". Integer cents in, no floats out. */
function percentText(numerator: number, denominator: number): { text: string; hundredths: number } {
  const hundredths = Math.round((numerator * 10000) / denominator);
  return { text: fromCents(hundredths), hundredths };
}

const figure = (value: string, unit: FigureUnit, working: WorkingStep[], evidence: EvidenceLink[]): AssetFigure => ({
  value,
  unit,
  working,
  evidence,
});

const money = (cents: number) => formatCents(cents);

interface Parts {
  id: string;
  caseId: string;
  at: string;
  run: AssetRun;
  obligations: AssetObligation[];
  transactions: AssetTransaction[];
}

/**
 * Everything the backend works out from the inputs: the figures with their working, the flags, and
 * the flags shown on each transaction. Called for the first run and again after every change, so
 * every figure on the screen always agrees with the rows beneath it.
 */
function assemble({ id, caseId, at, run, obligations, transactions }: Parts): AssetAnalysis {
  const scenarioEvidence: EvidenceLink = { label: "Loan scenario (entered by hand)" };
  const incomeEvidence: EvidenceLink = { label: "Candidate monthly income (income analysis)" };
  const balanceEvidence: EvidenceLink = {
    label: "Bank statement, Sep 2026, account ending 6032",
    document_id: BANK_DOC_DANIEL_ID,
    page: 3,
    line_ids: ["p3-L12"],
  };

  const assets = toCents(CLOSING_BALANCE);
  const needed = toCents(run.scenario.funds_to_close);
  const shortfall = Math.max(0, needed - assets);
  const housing = toCents(run.scenario.proposed_housing_payment);
  const income = toCents(run.candidate_monthly);
  const counted = obligations.filter((o) => o.counts_toward_dti);
  const obligationsTotal = counted.reduce((sum, o) => sum + toCents(o.monthly_payment), 0);

  const documented_assets = figure(CLOSING_BALANCE, "money", [
    {
      label: "Documented liquid assets",
      formula: `Closing balance, account ending ${ACCOUNT}, 30 Sep 2026`,
      result: money(assets),
      note: "The balance on the newest statement of each account",
    },
  ], [balanceEvidence]);

  const funds_to_close = figure(fromCents(needed), "money", [
    { label: "Funds needed to close", formula: "Entered with the loan scenario", result: money(needed) },
  ], [scenarioEvidence]);

  const funds_shortfall = figure(fromCents(shortfall), "money", [
    {
      label: "Shortfall",
      formula: `${money(needed)} − ${money(assets)}`,
      result: money(shortfall),
      note: "Funds needed less documented assets, and zero when the assets cover them",
    },
  ], [scenarioEvidence, balanceEvidence]);

  const monthly_obligations = figure(
    fromCents(obligationsTotal),
    "money",
    [
      {
        label: "Monthly obligations that count toward the DTI",
        formula: counted.length ? counted.map((o) => money(toCents(o.monthly_payment))).join(" + ") : "No obligation counts",
        result: money(obligationsTotal),
        note: "The underwriter decides which obligations count",
      },
    ],
    [{ label: "Obligations table below" }],
  );

  const ratioEvidence = [scenarioEvidence, incomeEvidence];
  const front = income > 0 ? percentText(housing, income) : null;
  const dtiParts = income > 0 ? percentText(housing + obligationsTotal, income) : null;
  const loan = toCents(run.scenario.loan_amount);
  const value = toCents(run.scenario.property_value);
  const ltvParts = value > 0 ? percentText(loan, value) : null;

  const front_end_ratio = front
    ? figure(front.text, "percent", [
        { label: "Front-end ratio", formula: `${money(housing)} ÷ ${money(income)} × 100`, result: `${front.text}%`, note: "Proposed housing payment over candidate monthly income" },
      ], ratioEvidence)
    : null;
  const dti = dtiParts
    ? figure(dtiParts.text, "percent", [
        {
          label: "DTI",
          formula: `(${money(housing)} + ${money(obligationsTotal)}) ÷ ${money(income)} × 100`,
          result: `${dtiParts.text}%`,
          note: "Housing payment plus counted obligations, over candidate monthly income",
        },
      ], [...ratioEvidence, { label: "Obligations table below" }])
    : null;
  const ltv = ltvParts
    ? figure(ltvParts.text, "percent", [
        { label: "LTV", formula: `${money(loan)} ÷ ${money(value)} × 100`, result: `${ltvParts.text}%`, note: "Loan amount over property value" },
      ], [scenarioEvidence])
    : null;

  const other_figures: OtherFigure[] = [];
  if (run.overtime_monthly && income > 0) {
    const withOvertime = income + toCents(run.overtime_monthly);
    const alt = percentText(housing + obligationsTotal, withOvertime);
    other_figures.push({
      id: "dti_with_overtime",
      label: "DTI if overtime were counted",
      figure: figure(alt.text, "percent", [
        {
          label: "DTI with overtime counted",
          formula: `(${money(housing)} + ${money(obligationsTotal)}) ÷ ${money(withOvertime)} × 100`,
          result: `${alt.text}%`,
          note: "Shown so the underwriter can test it. Whether overtime counts is a decision for a person",
        },
      ], [...ratioEvidence, { label: "Overtime a month (income analysis)" }]),
    });
  }

  // Flags, from the same templates the backend uses (backend/config/thresholds.yaml).
  const flags: AssetFlag[] = [];
  const withFlags = transactions.map((t) => ({ ...t, flags: [] as AssetTransaction["flags"] }));
  withFlags.forEach((t, i) => {
    if (t.direction === "credit" && toCents(t.amount) >= LARGE_DEPOSIT_FROM && t.category !== "payroll deposit") {
      const message = `Large deposit of ${money(toCents(t.amount))} on ${t.posted_on} — source may need documenting under program rules.`;
      flags.push({
        code: "AL-W101",
        severity: "warning",
        message,
        status: t.sourced ? "resolved" : "open",
        working: t.sourced ? `Marked as sourced: ${t.sourced_note ?? ""}`.trim() : null,
        evidence: [bankLine(i)],
      });
      t.flags.push({ code: "AL-W101", severity: "warning", message });
    }
  });
  if (shortfall > 0) {
    flags.push({
      code: "AL-W105",
      severity: "warning",
      message: `Documented assets of ${money(assets)} are ${money(shortfall)} short of the ${money(needed)} needed to close.`,
      status: "open",
      working: `${money(needed)} − ${money(assets)} = ${money(shortfall)}`,
      evidence: [scenarioEvidence, balanceEvidence],
    });
  }
  if (dtiParts && dtiParts.hundredths > REVIEW_LEVEL) {
    flags.push({
      code: "AL-W106",
      severity: "warning",
      message: `DTI ${dtiParts.text}% is above the review level of 43%.`,
      status: "open",
      working: `${dtiParts.text}% against the illustrative review level of 43%`,
      evidence: ratioEvidence,
    });
  }

  return {
    id,
    case_id: caseId,
    run_at: at,
    settings_label: "illustrative",
    note: NOTE,
    documented_assets,
    funds_to_close,
    funds_shortfall,
    monthly_obligations,
    front_end_ratio,
    dti,
    ltv,
    other_figures,
    obligations,
    transactions: withFlags,
    flags,
  };
}

/** The analysis a run produces for Daniel, from the loan scenario and the candidate income it read. */
export function buildDanielAssets(run: AssetRun, at: string, id = "a0000000-0000-4000-8000-000000000001"): AssetAnalysis {
  return assemble({ id, caseId: DANIEL_CASE_ID, at, run, obligations: baseObligations(), transactions: baseTransactions() });
}

const cleanReason = (reason: string | undefined): string => {
  const text = reason?.trim() ?? "";
  if (!text) throw new ApiError(422, "A reason is required");
  if (text.length > ASSET_REASON_MAX) throw new ApiError(422, `The reason can be at most ${ASSET_REASON_MAX} characters`);
  return text;
};

/**
 * PATCH .../transactions/{id}: give a line another category, or mark a deposit as sourced. The reason
 * is required. What the system chose stays in `system_category`; the person's change is kept beside it.
 * Returns a new analysis, with the flags worked out again.
 */
export function applyTransactionReview(
  analysis: AssetAnalysis,
  run: AssetRun,
  id: string,
  review: TransactionReview,
  by: string,
  at: string,
): AssetAnalysis {
  const reason = cleanReason(review.reason);
  if ((review.category === undefined) === (review.sourced === undefined)) {
    throw new ApiError(422, "Send either a category or sourced, not both and not neither");
  }
  const target = analysis.transactions.find((t) => t.id === id);
  if (!target) throw new ApiError(404, "Transaction not found");

  let next: AssetTransaction;
  if (review.category !== undefined) {
    if (!TRANSACTION_CATEGORIES.some((c) => c.value === review.category)) throw new ApiError(422, "Unknown category");
    next = { ...target, category: review.category, category_source: "user", needs_review: false, change: { reason, by, at } };
  } else {
    if (target.direction !== "credit") throw new ApiError(422, "Only a deposit can be marked as sourced");
    next = {
      ...target,
      sourced: review.sourced === true,
      sourced_note: review.sourced ? reason : null,
      change: { reason, by, at },
    };
  }
  return assemble({
    id: analysis.id,
    caseId: analysis.case_id,
    at: analysis.run_at,
    run,
    obligations: analysis.obligations,
    transactions: analysis.transactions.map((t) => (t.id === id ? next : t)),
  });
}

/**
 * PATCH .../obligations/{id}: count a debt toward the DTI or leave it out, reason required. The
 * obligations total and the ratios are worked out again at once. The system's own answer is kept.
 */
export function applyObligationReview(
  analysis: AssetAnalysis,
  run: AssetRun,
  id: string,
  review: ObligationReview,
  by: string,
  at: string,
): AssetAnalysis {
  const reason = cleanReason(review.reason);
  const target = analysis.obligations.find((o) => o.id === id);
  if (!target) throw new ApiError(404, "Obligation not found");
  const next: AssetObligation = { ...target, counts_toward_dti: review.counts_toward_dti, change: { reason, by, at } };
  return assemble({
    id: analysis.id,
    caseId: analysis.case_id,
    at: analysis.run_at,
    run,
    obligations: analysis.obligations.map((o) => (o.id === id ? next : o)),
    transactions: analysis.transactions,
  });
}

/**
 * PUT .../loan-scenario: the sample loan, entered by hand. The same rules as the backend (amounts with
 * up to two decimals, a property value above zero), refused with 422 and the first problem.
 */
export function checkScenario(input: LoanScenarioInput): LoanScenarioInput {
  const errors = validateScenario(input);
  const first = Object.values(errors)[0];
  if (first) throw new ApiError(422, first);
  return {
    purpose: input.purpose.trim(),
    occupancy: input.occupancy.trim(),
    property_value: input.property_value.trim(),
    loan_amount: input.loan_amount.trim(),
    proposed_housing_payment: input.proposed_housing_payment.trim(),
    funds_to_close: input.funds_to_close.trim(),
  };
}

export const seededScenario = (caseId: string): LoanScenario | null =>
  caseId === DANIEL_CASE_ID ? { ...DANIEL_SCENARIO, updated_at: null } : null;
