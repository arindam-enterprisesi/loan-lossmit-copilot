import { describe, expect, it } from "vitest";
import type { AgentRun, Condition, Finding, WaterfallOption } from "./copilot-types";
import {
  agentSteps,
  agentsBusy,
  conditionValue,
  evidenceLink,
  groupByPriority,
  OVERRIDE_STATUS_OPTIONS,
  settingLabel,
  settingValue,
  SIGN_OFF_STATEMENT,
  snapshotLabel,
  snapshotValue,
  undecidedCount,
  valueLabel,
  waterfallCards,
} from "./copilot";

const finding = (id: string, priority: Finding["priority"]): Finding => ({ id, priority, title: id, detail: "", evidence: [] });
const run = (agent: AgentRun["agent"], status: AgentRun["status"]): AgentRun => ({
  agent,
  attempt: 1,
  status,
  summary: null,
  error: null,
  started_at: null,
  finished_at: null,
});
const option = (key: WaterfallOption["option"], order_no: number, status: WaterfallOption["status"]): WaterfallOption => ({
  option: key,
  order_no,
  status,
  original_status: status,
  conditions: [],
  overridden: false,
});

describe("the sign-off statement", () => {
  it("is the words the brief gives, and no decision", () => {
    expect(SIGN_OFF_STATEMENT).toBe("Records a review. Not a decision.");
  });
});

describe("findings grouped by priority", () => {
  it("puts significant first, then attention, then information, and keeps the order inside a group", () => {
    const groups = groupByPriority([finding("a", "information"), finding("b", "significant"), finding("c", "attention"), finding("d", "significant")]);
    expect(groups.map((g) => g.priority)).toEqual(["significant", "attention", "information"]);
    expect(groups[0].items.map((f) => f.id)).toEqual(["b", "d"]);
  });

  it("leaves out a priority with no findings", () => {
    expect(groupByPriority([finding("a", "attention")]).map((g) => g.priority)).toEqual(["attention"]);
    expect(groupByPriority([])).toEqual([]);
  });
});

describe("conditions nobody has reviewed", () => {
  it("counts the pending ones", () => {
    const c = (decision: Condition["decision"]) => ({ decision }) as Condition;
    expect(undecidedCount([c("pending"), c("accepted"), c("pending"), c("rejected")])).toBe(2);
    expect(undecidedCount([])).toBe(0);
  });
});

describe("the three agents", () => {
  it("are listed in order, with a waiting row for any that has none yet", () => {
    const steps = agentSteps([run("writer", "running")]);
    expect(steps.map((s) => [s.agent, s.status])).toEqual([
      ["researcher", "waiting"],
      ["writer", "running"],
      ["critic", "waiting"],
    ]);
  });

  it("are busy while any is waiting or running, and not when all are done or failed", () => {
    expect(agentsBusy([run("researcher", "done"), run("writer", "running")])).toBe(true);
    expect(agentsBusy([run("researcher", "waiting")])).toBe(true);
    expect(agentsBusy([run("researcher", "done"), run("writer", "done"), run("critic", "failed")])).toBe(false);
    expect(agentsBusy([])).toBe(false);
  });
});

describe("evidence links", () => {
  it("send a calculation to the screen that shows it, and name it in words", () => {
    expect(evidenceLink({ kind: "calculation", id: "dti" }, "underwriting", "c1")).toMatchObject({ label: "DTI", href: "/underwriting/assets-liabilities" });
    expect(evidenceLink({ kind: "calculation", id: "dti_with_overtime" }, "underwriting", "c1").label).toBe("DTI with overtime counted");
  });

  it("show a calculation no screen has as plain words, with no link", () => {
    expect(evidenceLink({ kind: "calculation", id: "months_since_late_payment" }, "underwriting", "c1")).toMatchObject({
      label: "Months since the late payment",
      href: null,
    });
    expect(evidenceLink({ kind: "calculation", id: "some_new_figure" }, "underwriting", "c1")).toMatchObject({ label: "Some new figure", href: null });
  });

  it("send a rule to the feature that raised it", () => {
    expect(evidenceLink({ kind: "rule", id: "AL-W106" }, "underwriting", "c1")).toMatchObject({ label: "Rule AL-W106", href: "/underwriting/assets-liabilities" });
    expect(evidenceLink({ kind: "rule", id: "INC-W101" }, "underwriting", "c1").href).toBe("/underwriting/income-analysis");
    expect(evidenceLink({ kind: "rule", id: "DI-W701" }, "underwriting", "c1").href).toBe("/underwriting/document-intelligence");
    expect(evidenceLink({ kind: "rule", id: "XX-1" }, "underwriting", "c1").href).toBeNull();
  });

  it("send a checklist item to the case's documents, and a document to its review screen", () => {
    expect(evidenceLink({ kind: "checklist", id: "pay_stubs_30_days" }, "underwriting", "c1")).toMatchObject({
      label: "Checklist: Pay stubs 30 days",
      href: "/underwriting/document-intelligence/c1",
    });
    expect(evidenceLink({ kind: "document", id: "d9" }, "underwriting", "c1").href).toBe("/underwriting/document-intelligence/c1/d9");
    expect(evidenceLink({ kind: "document", id: "d9" }, "loss-mitigation", "c2").href).toBe("/loss-mitigation/document-intake/c2/d9");
  });

  it("leave a passage to the passage panel", () => {
    expect(evidenceLink({ kind: "passage", id: "p1" }, "underwriting", "c1")).toMatchObject({ label: "Guideline passage", href: null });
  });
});

describe("the report snapshot", () => {
  it("names each item, and puts separators in amounts only", () => {
    expect(snapshotLabel("candidate_monthly_income")).toBe("Candidate monthly income");
    expect(snapshotLabel("something_new")).toBe("Something new");
    expect(snapshotValue("property_value", "400000.00")).toBe("400,000.00");
    expect(snapshotValue("dti", "44.70%")).toBe("44.70%");
    expect(snapshotValue("borrower", "Daniel Reyes")).toBe("Daniel Reyes");
  });
});

describe("the waterfall cards", () => {
  it("are in order, one per option, with short sale and deed-in-lieu together when both are not reached", () => {
    const cards = waterfallCards([
      option("deed_in_lieu", 6, "not_reached"),
      option("repayment_plan", 1, "not_met"),
      option("short_sale", 5, "not_reached"),
      option("loan_modification", 4, "met"),
    ]);
    expect(cards.map((c) => [c.title, c.position, c.status])).toEqual([
      ["Repayment plan", "1", "not_met"],
      ["Loan modification", "4", "met"],
      ["Short sale and deed-in-lieu", "5–6", "not_reached"],
    ]);
    expect(cards[2].options.map((o) => o.option)).toEqual(["short_sale", "deed_in_lieu"]);
  });

  it("show short sale and deed-in-lieu apart once their statuses differ", () => {
    const cards = waterfallCards([option("short_sale", 5, "not_evaluable"), option("deed_in_lieu", 6, "not_reached")]);
    expect(cards.map((c) => c.title)).toEqual(["Short sale", "Deed-in-lieu"]);
  });
});

describe("the values a rule used", () => {
  it("name each one, and put separators in amounts, leaving counts and words as they are", () => {
    expect(valueLabel("gross_monthly_income")).toBe("Documented gross monthly income");
    expect(valueLabel("new_value")).toBe("New value");
    expect(conditionValue("arrears", "5160.00")).toBe("5,160.00");
    expect(conditionValue("surplus", "-70.00")).toBe("-70.00");
    expect(conditionValue("months_delinquent", "3")).toBe("3");
    expect(conditionValue("duration", "long_term")).toBe("Long term");
    expect(conditionValue("intent", "keep")).toBe("Keep");
  });
});

describe("the lender view settings", () => {
  it("name each setting and show it in its unit", () => {
    expect(settingLabel("liquidation_discount_pct")).toBe("Liquidation discount");
    expect(settingValue("liquidation_discount_pct", 15)).toBe("15%");
    expect(settingValue("redefault_chance_pct", "30")).toBe("30%");
    expect(settingValue("horizon_months", 36)).toBe("36 months");
    expect(settingValue("property_value", "265000.00")).toBe("265,000.00");
    expect(settingValue("foreclosure_and_carrying_costs", "24000.00")).toBe("24,000.00");
  });
});

describe("what a person may set when overriding", () => {
  it("is every status except 'not reached', which the waterfall sets", () => {
    expect(OVERRIDE_STATUS_OPTIONS.map((o) => o.value)).toEqual(["met", "not_met", "needs_confirmation", "not_evaluable"]);
  });
});
