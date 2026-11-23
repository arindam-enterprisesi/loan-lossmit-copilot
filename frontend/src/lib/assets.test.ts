import { describe, expect, it } from "vitest";
import {
  accountLabel,
  canMarkSourced,
  categoryLabel,
  figureText,
  groupByAccount,
  needsAttention,
  optionsWith,
  TRANSACTION_CATEGORIES,
  validateScenario,
} from "./assets";
import type { AssetTransaction, LoanScenarioInput } from "./assets-types";

const tx = (over: Partial<AssetTransaction> = {}): AssetTransaction => ({
  id: "t1",
  document_id: "d1",
  line_id: "p1-L8",
  account_last4: "6032",
  posted_on: "2026-09-01",
  description: "OAKMONT",
  amount: "-1425.00",
  direction: "debit",
  category: "housing payment",
  category_source: "ai",
  system_category: "housing payment",
  counterparty: null,
  needs_review: false,
  sourced: false,
  sourced_note: null,
  change: null,
  payroll_match: null,
  flags: [],
  ...over,
});

const scenario = (over: Partial<LoanScenarioInput> = {}): LoanScenarioInput => ({
  purpose: "purchase",
  occupancy: "primary residence",
  property_value: "400000.00",
  loan_amount: "360000.00",
  proposed_housing_payment: "1980.00",
  funds_to_close: "36500.00",
  ...over,
});

describe("figureText", () => {
  it("adds separators to money and a percent sign to a ratio", () => {
    expect(figureText({ value: "9226.32", unit: "money", working: [], evidence: [] })).toBe("9,226.32");
    expect(figureText({ value: "44.70", unit: "percent", working: [], evidence: [] })).toBe("44.70%");
    expect(figureText({ value: "-70.00", unit: "money", working: [], evidence: [] })).toBe("-70.00");
  });

  it("shows a dash when there is no figure", () => {
    expect(figureText(null)).toBe("—");
    expect(figureText(undefined)).toBe("—");
  });
});

describe("categories", () => {
  it("lists the fourteen categories of Feature Design 3.5, with readable labels", () => {
    expect(TRANSACTION_CATEGORIES).toHaveLength(14);
    expect(categoryLabel("overdraft or returned-item fee")).toBe("Overdraft or returned-item fee");
    expect(categoryLabel("payroll deposit")).toBe("Payroll deposit");
  });
});

describe("grouping and attention", () => {
  it("groups lines by account in the order accounts first appear, keeping each account's line order", () => {
    const groups = groupByAccount([
      tx({ id: "a", account_last4: "6032" }),
      tx({ id: "b", account_last4: "1111" }),
      tx({ id: "c", account_last4: "6032" }),
      tx({ id: "d", account_last4: null }),
    ]);
    expect(groups.map((g) => [g.account, g.transactions.map((t) => t.id)])).toEqual([
      ["6032", ["a", "c"]],
      ["1111", ["b"]],
      [null, ["d"]],
    ]);
  });

  it("names an account by its last four digits, and one with no number plainly", () => {
    expect(accountLabel("6032")).toBe("Account ending 6032");
    expect(accountLabel(null)).toBe("Account not named");
  });

  it("a line needs a look when it carries a flag or could not be labelled", () => {
    expect(needsAttention(tx())).toBe(false);
    expect(needsAttention(tx({ needs_review: true }))).toBe(true);
    expect(needsAttention(tx({ flags: [{ code: "AL-W101", severity: "warning", message: "m" }] }))).toBe(true);
  });

  it("only a deposit can be marked as sourced", () => {
    expect(canMarkSourced(tx({ direction: "credit" }))).toBe(true);
    expect(canMarkSourced(tx({ direction: "debit" }))).toBe(false);
  });
});

describe("the options in the scenario form", () => {
  it("adds a value the backend already holds, so it is never lost", () => {
    expect(optionsWith(["a", "b"], "b")).toEqual(["a", "b"]);
    expect(optionsWith(["a", "b"], "c")).toEqual(["a", "b", "c"]);
    expect(optionsWith(["a", "b"], "")).toEqual(["a", "b"]);
  });
});

describe("validateScenario: the backend's rules, checked before sending", () => {
  it("accepts Daniel's sample loan", () => {
    expect(validateScenario(scenario())).toEqual({});
  });

  it("asks for a purpose and an occupancy", () => {
    expect(validateScenario(scenario({ purpose: " ", occupancy: "" }))).toEqual({
      purpose: "Choose the loan purpose",
      occupancy: "Choose the occupancy",
    });
  });

  it("wants plain amounts: digits with up to two decimals", () => {
    for (const bad of ["", "lots", "-5", "1,000.00", "36500.123", "1e5", "$100", "12345678901"]) {
      expect(validateScenario(scenario({ funds_to_close: bad })).funds_to_close).toBe("Enter an amount such as 400000.00");
    }
    for (const ok of ["0", "0.00", "36500", "36500.5", "36500.50", " 36500.00 "]) {
      expect(validateScenario(scenario({ funds_to_close: ok })).funds_to_close).toBeUndefined();
    }
  });

  it("a property value must be more than zero, the other amounts may be zero", () => {
    expect(validateScenario(scenario({ property_value: "0" })).property_value).toBe("Must be more than zero");
    expect(validateScenario(scenario({ property_value: "0.00" })).property_value).toBe("Must be more than zero");
    expect(validateScenario(scenario({ loan_amount: "0" })).loan_amount).toBeUndefined();
    expect(validateScenario(scenario({ proposed_housing_payment: "0.00" })).proposed_housing_payment).toBeUndefined();
  });

  it("reports every problem at once", () => {
    const errors = validateScenario({ purpose: "", occupancy: "", property_value: "", loan_amount: "", proposed_housing_payment: "", funds_to_close: "" });
    expect(Object.keys(errors)).toHaveLength(6);
  });
});
