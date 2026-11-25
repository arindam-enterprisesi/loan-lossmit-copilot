// A sample of what the real backend sends for Daniel Reyes's asset and liability analysis, written from
// backend/app/api/schemas/assets.py (on `main` since PR #12) and the figures in
// data/synthetic/scenarios/daniel_reyes.json. It is test data for the translation in assets-real.ts,
// not a mock the screens use. Replace it with a recorded real answer once the backend runs.
import type { RealCalc, RealRef } from "./calc-real";
import type { RealAssetAnalysis, RealLoanScenario, RealObligation, RealTransaction } from "./assets-real";

export const SAMPLE_BANK_ID = "11111111-1111-4111-8111-bbbbbbbbbbbb";
export const SAMPLE_CASE_ID = "11111111-1111-4111-8111-111111111111";

const ref = (field: string, lines: string[], document_id: string | null = SAMPLE_BANK_ID): RealRef => ({
  document_id,
  field,
  line_ids: lines,
});

const calc = (
  name: string,
  value: string,
  unit: string,
  formula: string,
  working: string,
  evidence: RealRef[] = [],
): RealCalc => ({
  id: `calc-${name}`,
  name,
  value,
  unit,
  formula,
  inputs: {},
  working,
  config_version: "thresholds@2026-11-19.1",
  evidence,
});

const tx = (
  n: number,
  line: string,
  posted_on: string,
  description: string,
  amount: string,
  direction: "credit" | "debit",
  category: RealTransaction["category"],
  counterparty: string,
  extra: Partial<RealTransaction> = {},
): RealTransaction => ({
  id: `44444444-4444-4444-8444-${String(n).padStart(12, "0")}`,
  document_id: SAMPLE_BANK_ID,
  line_id: line,
  account_last4: "6032",
  posted_on,
  description,
  amount,
  direction,
  category,
  category_source: "ai",
  system_category: category,
  counterparty,
  needs_review: false,
  sourced: false,
  sourced_note: null,
  change: null,
  payroll_match: null,
  large_deposit: null,
  ...extra,
});

const ob = (
  n: number,
  creditor: string,
  kind: string,
  payment: string,
  balance: string | null,
  source: RealObligation["source"],
  counts: boolean,
  reason: string,
): RealObligation => ({
  id: `55555555-5555-4555-8555-${String(n).padStart(12, "0")}`,
  creditor,
  kind,
  monthly_payment: payment,
  balance,
  source,
  counts_toward_dti: counts,
  reason,
  system_counts_toward_dti: counts,
  change: null,
});

export function realDanielAssets(): RealAssetAnalysis {
  return {
    id: "99999999-9999-4999-8999-000000000002",
    case_id: SAMPLE_CASE_ID,
    status: "succeeded",
    started_at: "2026-11-23T09:00:00Z",
    finished_at: "2026-11-23T09:00:04Z",
    config_versions: { thresholds: { version: "2026-11-19.1", label: "illustrative" } },
    note: "Candidate figures for the underwriter to review. They are not a decision.",
    // A single-term sum is written without " = ", as the backend does for one balance.
    documented_assets: calc("documented_assets", "9226.32", "usd", "sum of the closing balances on the newest statements", "9,226.32", [
      ref("closing_balance", ["p3-L12"]),
    ]),
    funds_to_close: calc("funds_to_close", "36500.00", "usd", "funds needed to close, from the loan scenario", "36,500.00", [
      { source: "loan_scenario", line_ids: [] },
    ]),
    funds_shortfall: calc("funds_shortfall", "27273.68", "usd", "funds needed - documented assets", "36,500.00 - 9,226.32 = 27,273.68"),
    monthly_obligations: calc(
      "monthly_obligations",
      "693.00",
      "usd",
      "sum of the monthly payments of obligations that count toward DTI",
      "88.00 + 40.00 + 35.00 + 420.00 + 110.00 = 693.00",
    ),
    front_end_ratio: calc("front_end_ratio", "0.331104", "ratio", "proposed housing payment / candidate monthly income", "1,980.00 / 5,980.00 = 33.11%", [
      { source: "loan_scenario", line_ids: [] },
      { calculation: "candidate_monthly_income", line_ids: [] },
    ]),
    dti: calc("dti", "0.446990", "ratio", "(proposed housing payment + monthly obligations) / candidate monthly income", "(1,980.00 + 693.00) / 5,980.00 = 44.70%"),
    ltv: calc("ltv", "0.900000", "ratio", "loan amount / property value", "360,000.00 / 400,000.00 = 90.00%"),
    calculations: [
      calc("dti_with_overtime", "0.416060", "ratio", "DTI with overtime counted", "(1,980.00 + 693.00) / 6,424.41 = 41.61%"),
      calc("extra_obligation_monthly", "0.00", "usd", "extra obligations", "0.00"), // not a what-if: not shown
    ],
    obligations: [
      ob(1, "Northgate Card", "credit card", "88.00", "2940.00", "both", true, "On the credit report and in the bank statements."),
      ob(2, "Harbor Retail Card", "credit card", "35.00", "300.00", "credit_report", true, "Credit report liability with a monthly payment above zero."),
      ob(3, "Oakmont Apartments", "rent", "1425.00", null, "bank", false, "Current rent on a purchase of a primary residence."),
    ],
    transactions: [
      tx(1, "p1-L8", "2026-09-01", "OAKMONT APARTMENTS RENT", "1425.00", "debit", "housing payment", "Oakmont Apartments"),
      tx(2, "p1-L9", "2026-09-04", "CEDAR VALLEY MFG PAYROLL", "2033.61", "credit", "payroll deposit", "Cedar Valley Manufacturing", {
        payroll_match: calc("payroll_match", "2033.61", "usd", "net pay on the stub", "Net pay 2,033.61 matches the pay stub for 2026-09-04"),
      }),
      tx(3, "p1-L14", "2026-09-06", "TARGET T-1124", "29.67", "debit", "other", "Target", {
        category: "everyday spending",
        category_source: "user",
        change: { reason: "A grocery run", by: "user-1", at: "2026-11-23T10:00:00Z" },
      }),
      tx(4, "p2-L10", "2026-09-22", "ZELLE FROM PATRICIA OWENS REF 8841", "2000.00", "credit", "transfer in", "Patricia Owens", {
        large_deposit: calc("large_deposit", "2000.00", "usd", "credit of 1,000.00 or more that is not payroll", "2,000.00 is at least 1,000.00"),
      }),
    ],
    flags: [
      {
        id: "flag-1",
        code: "AL-W101",
        severity: "warning",
        message: "Large deposit of 2,000.00 on 2026-09-22 — source may need documenting under program rules.",
        status: "open",
        working: null,
        refs: [ref("transaction", ["p2-L10"])],
      },
      {
        id: "flag-2",
        code: "AL-W105",
        severity: "warning",
        message: "Documented assets of 9,226.32 are 27,273.68 short of the 36,500.00 needed to close.",
        status: "open",
        working: "36,500.00 - 9,226.32 = 27,273.68",
        refs: [],
      },
      {
        id: "flag-3",
        code: "AL-W106",
        severity: "warning",
        message: "DTI 44.70% is above the review level of 43%.",
        status: "open",
        working: null,
        refs: [],
      },
    ],
  };
}

export function realDanielScenario(): RealLoanScenario {
  return {
    case_id: SAMPLE_CASE_ID,
    purpose: "purchase",
    occupancy: "primary residence",
    property_value: "400000.00",
    loan_amount: "360000.00",
    proposed_housing_payment: "1980.00",
    funds_to_close: "36500.00",
    updated_at: "2026-11-23T08:00:00Z",
  };
}
