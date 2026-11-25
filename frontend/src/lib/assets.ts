// Small display helpers for the Assets and liabilities screen. No calculation: the backend returns every
// figure with its working, and these only turn that text into things to show.
import { formatMoney } from "./format";
import type {
  AssetFigure,
  AssetTransaction,
  LoanScenarioInput,
  ObligationSource,
  TransactionCategory,
} from "./assets-types";

/** The wording the brief requires on every figure. */
export const CANDIDATE_RATIO_LABEL = "candidate - for underwriter review";

/** The longest reason accepted for a change (same limit as the other screens). */
export const ASSET_REASON_MAX = 500;

/** The categories in the order of Feature Design 3.5, with the words shown on a chip. */
export const TRANSACTION_CATEGORIES: { value: TransactionCategory; label: string }[] = [
  { value: "payroll deposit", label: "Payroll deposit" },
  { value: "other income deposit", label: "Other income deposit" },
  { value: "transfer in", label: "Transfer in" },
  { value: "transfer out", label: "Transfer out" },
  { value: "housing payment", label: "Housing payment" },
  { value: "loan payment", label: "Loan payment" },
  { value: "credit card payment", label: "Credit card payment" },
  { value: "utility", label: "Utility" },
  { value: "insurance", label: "Insurance" },
  { value: "everyday spending", label: "Everyday spending" },
  { value: "overdraft or returned-item fee", label: "Overdraft or returned-item fee" },
  { value: "other fee", label: "Other fee" },
  { value: "refund", label: "Refund" },
  { value: "other", label: "Other" },
];

export const categoryLabel = (category: TransactionCategory): string =>
  TRANSACTION_CATEGORIES.find((c) => c.value === category)?.label ?? category;

/** The short words on a flag chip. The full sentence is the flag's message. */
export const FLAG_SHORT_LABEL: Record<string, string> = {
  "AL-W101": "Large deposit",
  "AL-W102": "Fee",
  "AL-W103": "Not on credit report",
  "AL-W104": "No pay stub match",
};

export const SOURCE_LABEL: Record<ObligationSource, string> = {
  bank: "Bank statements",
  credit_report: "Credit report",
  both: "Bank and credit report",
};

/** A figure as text: money gets separators, a percentage gets a % sign. Only text is changed. */
export function figureText(figure: AssetFigure | null | undefined): string {
  if (!figure) return "—";
  return figure.unit === "percent" ? `${formatMoney(figure.value)}%` : formatMoney(figure.value);
}

/** The "Account ending 6032" heading for one group of lines. */
export const accountLabel = (last4: string | null): string => (last4 ? `Account ending ${last4}` : "Account not named");

/** The lines of each account, in the order the accounts first appear. Lines keep their order. */
export function groupByAccount(transactions: AssetTransaction[]): { account: string | null; transactions: AssetTransaction[] }[] {
  const groups = new Map<string | null, AssetTransaction[]>();
  for (const t of transactions) {
    const list = groups.get(t.account_last4) ?? [];
    list.push(t);
    groups.set(t.account_last4, list);
  }
  return [...groups.entries()].map(([account, list]) => ({ account, transactions: list }));
}

/** A line that deserves a look: it carries a flag, or the model could not label it. */
export const needsAttention = (t: AssetTransaction): boolean => t.needs_review || t.flags.length > 0;

/** Only a deposit (money in) can be marked as sourced. */
export const canMarkSourced = (t: AssetTransaction): boolean => t.direction === "credit";

/** The loan purposes and occupancies the form lists. A value the backend already holds is added when shown. */
export const LOAN_PURPOSES = ["purchase", "refinance", "cash-out refinance"];
export const OCCUPANCIES = ["primary residence", "second home", "investment property"];

export const optionsWith = (options: string[], current: string): string[] =>
  current && !options.includes(current) ? [...options, current] : options;

/** A money amount the backend accepts: digits with up to two decimals, at most 10 digits before the point. */
export const SCENARIO_AMOUNT = /^\d{1,10}(\.\d{1,2})?$/;
const IS_ZERO = /^0+(\.0+)?$/;

export type ScenarioErrors = Partial<Record<keyof LoanScenarioInput, string>>;

/**
 * The same rules the backend applies (backend/app/api/schemas/assets.py: LoanScenarioIn), so a person
 * hears about a mistake before sending. The backend still checks, and answers 422 if it disagrees.
 */
export function validateScenario(v: LoanScenarioInput): ScenarioErrors {
  const errors: ScenarioErrors = {};
  if (!v.purpose.trim()) errors.purpose = "Choose the loan purpose";
  if (!v.occupancy.trim()) errors.occupancy = "Choose the occupancy";
  const amount = (key: "property_value" | "loan_amount" | "proposed_housing_payment" | "funds_to_close", mustBePositive: boolean) => {
    const text = v[key].trim();
    if (!SCENARIO_AMOUNT.test(text)) errors[key] = "Enter an amount such as 400000.00";
    else if (mustBePositive && IS_ZERO.test(text)) errors[key] = "Must be more than zero";
  };
  amount("property_value", true);
  amount("loan_amount", false);
  amount("proposed_housing_payment", false);
  amount("funds_to_close", false);
  return errors;
}
