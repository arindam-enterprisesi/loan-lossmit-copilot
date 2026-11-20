import { describe, expect, it } from "vitest";
import {
  canOverride,
  CHECKLIST_BY_PILLAR,
  ITEM_STATUS_LABEL,
  ITEM_STATUS_TONE,
  outstandingText,
  overallLabel,
  type ChecklistItem,
} from "./completeness";

const item = (status: ChecklistItem["status"]): ChecklistItem => ({
  item_id: "x",
  label: "X",
  status,
  reason: "r",
});

describe("completeness helpers", () => {
  it("runs one checklist per menu section, the contract's example id for Loan Processing", () => {
    expect(CHECKLIST_BY_PILLAR.underwriting).toBe("pillar1-wage-earner@1");
    expect(Object.keys(CHECKLIST_BY_PILLAR).sort()).toEqual(["loss-mitigation", "underwriting"]);
  });

  it("gives every status a plain label and a colour", () => {
    expect(ITEM_STATUS_LABEL).toEqual({
      satisfied: "Satisfied",
      partial: "Partially satisfied",
      missing: "Missing",
      overridden: "Overridden",
    });
    expect(ITEM_STATUS_TONE).toEqual({ satisfied: "success", partial: "warning", missing: "danger", overridden: "info" });
  });

  it("only lets an item that is partly met or missing be overridden", () => {
    expect(canOverride(item("partial"))).toBe(true);
    expect(canOverride(item("missing"))).toBe(true);
    expect(canOverride(item("satisfied"))).toBe(false);
    expect(canOverride(item("overridden"))).toBe(false);
  });

  it("describes the overall status without making it a decision", () => {
    expect(overallLabel("incomplete")).toBe("Incomplete");
    expect(overallLabel("complete")).toBe("Complete for this checklist");
  });

  it("writes the outstanding items as a list ready to paste, or nothing when there are none", () => {
    expect(outstandingText(["W-2 for 2024", "Form 1040 for 2024"])).toBe(
      "Outstanding items for this case:\n- W-2 for 2024\n- Form 1040 for 2024",
    );
    expect(outstandingText([])).toBe("");
  });
});
