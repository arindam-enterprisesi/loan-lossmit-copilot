import { describe, expect, it } from "vitest";
import { ANGELA_CASE_ID } from "@/mocks/data";
import { adjustmentRequest, confirmationRequest, toHardshipAssessment } from "./hardship-real";
import { realAngelaHardship, SAMPLE_LETTER_ID, SAMPLE_STUB_ID } from "./hardship-real-sample";

const translated = () => toHardshipAssessment(realAngelaHardship(), ANGELA_CASE_ID);
const item = (a: ReturnType<typeof translated>, key: string) => a.profile.find((p) => p.key === key)!;
const measure = (a: ReturnType<typeof translated>, id: string) => a.measures.find((m) => m.id === id)!;

describe("the real hardship answer, translated for the screen: top level", () => {
  it("keeps the run, the case, the date and the setting label", () => {
    const a = translated();
    expect(a).toMatchObject({
      id: "99999999-9999-4999-8999-000000000001",
      case_id: ANGELA_CASE_ID,
      run_at: "2026-11-20T09:00:00Z",
      settings_label: "illustrative",
    });
  });
});

describe("the real hardship answer: the profile", () => {
  it("shows the reading: reduction in income, July 2026, unknown, keep", () => {
    const a = translated();
    expect(a.profile.map((p) => [p.key, p.label, p.value, p.value_label])).toEqual([
      ["primary_reason", "Primary reason", "reduction_in_income", "Reduction in income"],
      ["onset", "Onset", "2026-07", "July 2026"],
      ["duration", "Duration", "unknown", "Unknown"],
      ["intent", "Intent", "keep", "Keep the home"],
    ]);
  });

  it("carries each quote, its line and whether code verified it", () => {
    const a = translated();
    expect(item(a, "intent").quote).toEqual({ text: "I want to keep my home", line_ids: ["p1-L14"] });
    expect(a.profile.every((p) => p.quote_verified)).toBe(true);
  });

  it("reports a quote that was not verified, and an item with no quote", () => {
    const real = realAngelaHardship();
    real.profile.duration.verified = false;
    real.profile.intent.quote = null;
    const a = toHardshipAssessment(real, ANGELA_CASE_ID);
    expect(item(a, "duration").quote_verified).toBe(false);
    expect(item(a, "intent").quote).toBeNull();
  });

  it("offers a list for the reason, the duration and the intent, and none for the onset", () => {
    const a = translated();
    expect(item(a, "primary_reason").options).toHaveLength(9);
    expect(item(a, "duration").options?.map((o) => o.value)).toEqual(["temporary", "long_term", "unknown"]);
    expect(item(a, "intent").options?.map((o) => o.value)).toEqual(["keep", "sell", "unsure"]);
    expect(item(a, "onset").options).toBeNull();
    expect(a.profile.every((p) => p.review === null)).toBe(true);
  });

  it("shows the onset as it was stated when the letter did not make the month clear", () => {
    const real = realAngelaHardship();
    real.profile.onset.month = null;
    real.profile.onset.as_stated = "last summer";
    expect(item(toHardshipAssessment(real, ANGELA_CASE_ID), "onset")).toMatchObject({ value: "last summer", value_label: "last summer" });
    real.profile.onset.as_stated = null;
    expect(item(toHardshipAssessment(real, ANGELA_CASE_ID), "onset").value_label).toBe("Not stated");
  });

  it("a correction shows the confirmed value and keeps what the letter said, with who, when and why", () => {
    const real = realAngelaHardship();
    real.profile.duration.confirmation = {
      status: "corrected",
      value: "long_term",
      original: "unknown",
      reason: "Employer said the cut is permanent",
      by: "user-1",
      at: "2026-11-20T10:00:00Z",
      label: "reviewer-confirmed",
    };
    const duration = item(toHardshipAssessment(real, ANGELA_CASE_ID), "duration");
    expect(duration).toMatchObject({ value: "long_term", value_label: "Long-term" });
    expect(duration.review).toEqual({
      status: "corrected",
      reason: "Employer said the cut is permanent",
      by: "user-1",
      at: "2026-11-20T10:00:00Z",
      original_label: "Unknown",
    });
    expect(duration.quote?.text).toContain("I do not know whether my hours will return"); // the reading itself is untouched
  });

  it("a confirmation keeps the value and records the person", () => {
    const real = realAngelaHardship();
    real.profile.intent.confirmation = {
      status: "confirmed",
      value: "keep",
      original: null,
      reason: null,
      by: "user-1",
      at: "2026-11-20T10:00:00Z",
      label: "reviewer-confirmed",
    };
    const intent = item(toHardshipAssessment(real, ANGELA_CASE_ID), "intent");
    expect(intent.value_label).toBe("Keep the home");
    expect(intent.review).toMatchObject({ status: "confirmed", reason: null, original_label: "Keep the home" });
  });
});

describe("the real hardship answer: the letter", () => {
  it("has only the quoted lines, in letter order, and says so", () => {
    const a = translated();
    expect(a.letter.partial).toBe(true);
    expect(a.letter.document_id).toBe(SAMPLE_LETTER_ID);
    expect(a.letter.lines.map((l) => l.id)).toEqual(["p1-L6", "p1-L9", "p1-L14"]);
    // Two quotes sit on line 6; the onset quote is inside the reason quote, so the line reads once.
    expect(a.letter.lines[0].text).toBe("cut my hours from 40 to 30 a week in July");
  });

  it("puts a quote that runs over several lines on its first line", () => {
    const real = realAngelaHardship();
    real.profile.duration.lines = ["p1-L9", "p1-L10"];
    const a = toHardshipAssessment(real, ANGELA_CASE_ID);
    expect(a.letter.lines.find((l) => l.id === "p1-L10")?.text).toBe("…");
    expect(a.letter.lines.map((l) => l.id)).toEqual(["p1-L6", "p1-L9", "p1-L10", "p1-L14"]);
  });

  it("joins two different quotes on the same line", () => {
    const real = realAngelaHardship();
    real.profile.intent.lines = ["p1-L9"];
    const a = toHardshipAssessment(real, ANGELA_CASE_ID);
    expect(a.letter.lines.find((l) => l.id === "p1-L9")?.text).toBe(
      "I do not know whether my hours will return to 40 a week … I want to keep my home",
    );
  });

  it("has no link to a document when the backend names none", () => {
    const real = realAngelaHardship();
    real.letter_document_id = null;
    expect(toHardshipAssessment(real, ANGELA_CASE_ID).letter.document_id).toBe("");
  });
});

describe("the real hardship answer: the measures", () => {
  it("shows the surplus observed -280.00 with the stated -70.00 beside it", () => {
    const s = measure(translated(), "surplus");
    expect(s).toMatchObject({ label: "Monthly surplus (observed)", value: "-280.00", unit: "money" });
    expect(s.compare).toEqual({ label: "Stated", value: "-70.00", unit: "money" });
  });

  it("shows ratios as the backend's own percentage text, not as the six-place decimal", () => {
    const h = measure(translated(), "housing_ratio");
    expect(h).toMatchObject({ value: "40.95", unit: "percent" });
    expect(h.compare).toEqual({ label: "Before the cut", value: "30.71", unit: "percent" });
    expect(measure(translated(), "income_change")).toMatchObject({ value: "-25.00", unit: "percent" });
  });

  it("shows a ratio as it came, never multiplied, when the working has no percentage", () => {
    const real = realAngelaHardship();
    real.measures.find((c) => c.name === "housing_ratio")!.working = "1,720.00 / 4,200.00";
    expect(measure(toHardshipAssessment(real, ANGELA_CASE_ID), "housing_ratio")).toMatchObject({ value: "0.409524", unit: "money" });
  });

  it("shows arrears and liquid assets, with 12.41% of arrears as the note", () => {
    const a = translated();
    expect(measure(a, "arrears").value).toBe("5160.00");
    expect(measure(a, "liquid_assets")).toMatchObject({ value: "640.25", note: "12.41% of arrears" });
  });

  it("has no more than the five measures the screen shows, none of them flagged by the screen", () => {
    const a = translated();
    expect(a.measures.map((m) => m.id)).toEqual(["surplus", "housing_ratio", "arrears", "liquid_assets", "income_change"]);
    expect(a.measures.every((m) => !m.flagged && m.flag_message === null)).toBe(true);
  });

  it("cuts the backend's working into formula and result, and links the evidence", () => {
    const h = measure(translated(), "housing_ratio");
    expect(h.working[0]).toEqual({
      label: "Contractual payment / documented gross monthly income",
      formula: "1,720.00 / 4,200.00",
      result: "40.95%",
    });
    expect(h.working).toHaveLength(2); // the figure and the one before the cut
    expect(h.evidence).toEqual([{ label: "Regular monthly payment", document_id: SAMPLE_STUB_ID, line_ids: ["p1-L4"] }]);
  });

  it("leaves a measure out when the backend could not work it out", () => {
    const real = realAngelaHardship();
    real.measures = real.measures.filter((c) => c.name !== "arrears");
    expect(toHardshipAssessment(real, ANGELA_CASE_ID).measures.map((m) => m.id)).not.toContain("arrears");
  });
});

describe("the real hardship answer: the budget", () => {
  it("lists each category with stated and observed amounts, and flags only 'Other'", () => {
    const b = translated().budget;
    expect(b.lines.map((l) => [l.category, l.stated, l.observed, l.flagged])).toEqual([
      ["Housing", "1720.00", "1720.00", false],
      ["Utilities", "310.00", "310.00", false],
      ["Food", "780.00", "780.00", false],
      ["Loans", "410.00", "410.00", false],
      ["Other", "200.00", "410.00", true],
    ]);
  });

  it("shows the gap as the backend sent it, without adding a sign it cannot know", () => {
    const other = translated().budget.lines[4];
    expect(other.difference).toBe("210.00");
    expect(other.difference_unsigned).toBe(true);
  });

  it("uses the backend's sentence for the flag on the line it is about", () => {
    const lines = translated().budget.lines;
    expect(lines[4].flag_message).toBe("Observed other spending 410.00 against 200.00 stated — ask the borrower");
    expect(lines[0].flag_message).toBeNull();
  });

  it("takes the totals from the backend's measures and says which month the observed amounts are from", () => {
    const b = translated().budget;
    expect(b.stated_total).toBe("3420.00");
    expect(b.observed_total).toBe("3630.00");
    expect(b.observed_basis).toContain("July");
  });

  it("shows what counts after an adjustment, and keeps what the documents showed, with who, when and why", () => {
    const real = realAngelaHardship();
    const other = real.budget[4];
    other.adjusted = "200.00";
    other.adjustment_reason = "One-off car repair";
    other.effective_observed = "200.00";
    other.flagged = false;
    other.difference = "0.00";
    other.change = { reason: "One-off car repair", by: "user-1", at: "2026-11-20T10:00:00Z" };
    const line = toHardshipAssessment(real, ANGELA_CASE_ID).budget.lines[4];
    expect(line.observed).toBe("200.00");
    expect(line.adjustment).toEqual({
      original_observed: "410.00",
      reason: "One-off car repair",
      by: "user-1",
      at: "2026-11-20T10:00:00Z",
    });
  });

  it("shows a dash, not 0.00, for an amount the backend does not have", () => {
    const real = realAngelaHardship();
    real.budget[0].stated = null;
    expect(toHardshipAssessment(real, ANGELA_CASE_ID).budget.lines[0].stated).toBe("");
  });
});

describe("the real hardship answer: the consistency checks", () => {
  it("names each check and shows both sides with where each comes from", () => {
    const checks = translated().checks;
    expect(checks.map((c) => [c.id, c.label, c.status])).toEqual([
      ["check_income_stated_vs_documented", "Income: stated and documented", "consistent"],
      ["check_pay_vs_hours", "Hours cut against the change in pay", "consistent"],
      ["check_reason_vs_letter", "Reason: application and letter", "consistent"],
      ["check_intent_vs_letter", "Intent: application and letter", "consistent"],
    ]);
  });

  it("shows the hours and the pay as the percentages in the backend's sentence", () => {
    const hours = translated().checks[1];
    expect(hours.stated).toEqual({ value: "Hours changed by -25.00% (40 to 30 a week)", source: { label: "Hardship letter" } });
    expect(hours.documented).toEqual({ value: "Pay changed by -25.00%", source: { label: "Pay stubs" } });
    expect(hours.detail).toContain("They agree.");
  });

  it("shows the intent in words, and a difference as flagged", () => {
    const real = realAngelaHardship();
    const intent = real.checks[3];
    intent.agrees = false;
    intent.values = { application: "keep", letter: "sell" };
    const c = toHardshipAssessment(real, ANGELA_CASE_ID).checks[3];
    expect(c.status).toBe("flagged");
    expect(c.stated.value).toBe("Keep the home");
    expect(c.documented.value).toBe("Sell");
  });

  it("gives a check the backend added later a readable name", () => {
    const real = realAngelaHardship();
    real.checks.push({ name: "check_something_new", agrees: true, working: "ok", values: {} });
    expect(toHardshipAssessment(real, ANGELA_CASE_ID).checks[4].label).toBe("Something new");
  });
});

describe("what a person sends to the real backend", () => {
  it("names the item to confirm, with an empty body", () => {
    expect(confirmationRequest({ key: "intent", action: "confirm" })).toEqual({ intent: {} });
  });

  it("names the item to correct, with the value and the reason", () => {
    expect(confirmationRequest({ key: "onset", action: "correct", value: "2026-06", reason: "Pay stub" })).toEqual({
      onset: { value: "2026-06", reason: "Pay stub" },
    });
  });

  it("passes the backend's note that the budget is not worked out yet", () => {
    const real = realAngelaHardship();
    real.budget = [];
    real.measures = [];
    real.budget_note = "The budget has not been computed for this reading yet.";
    const a = toHardshipAssessment(real, ANGELA_CASE_ID);
    expect(a.budget_note).toBe("The budget has not been computed for this reading yet.");
    expect(a.budget.lines).toEqual([]);
    expect(a.measures).toEqual([]);
    expect(translated().budget_note).toBeNull();
  });

  it("a null amount clears an adjustment", () => {
    expect(adjustmentRequest({ amount: null, reason: "Not a one-off" })).toEqual({ adjusted_amount: null, reason: "Not a one-off" });
  });

  it("sends the adjusted amount as text, so nothing is rounded", () => {
    expect(adjustmentRequest({ amount: "200.00", reason: "One-off" })).toEqual({ adjusted_amount: "200.00", reason: "One-off" });
  });
});
