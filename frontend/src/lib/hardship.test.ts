import { describe, expect, it } from "vitest";
import { buildAngelaHardship } from "@/mocks/hardship";
import { AMOUNT_PATTERN, measureText, reviewLabel, signedMoney, splitLine } from "./hardship";
import type { ProfileItem } from "./hardship-types";

const assessment = () => buildAngelaHardship("2026-11-20T09:00:00.000Z");
const lineText = (a: ReturnType<typeof assessment>, id: string) => a.letter.lines.find((l) => l.id === id)!.text;

describe("measureText", () => {
  it("adds thousands separators to money and keeps the sign", () => {
    expect(measureText("5160.00", "money")).toBe("5,160.00");
    expect(measureText("-280.00", "money")).toBe("-280.00");
    expect(measureText("-1280.50", "money")).toBe("-1,280.50");
  });

  it("puts a percent sign on a ratio", () => {
    expect(measureText("40.95", "percent")).toBe("40.95%");
    expect(measureText("-25.00", "percent")).toBe("-25.00%");
  });
});

describe("signedMoney", () => {
  it("shows a plus sign only on a positive difference", () => {
    expect(signedMoney("210.00")).toBe("+210.00");
    expect(signedMoney("1500.00")).toBe("+1,500.00");
    expect(signedMoney("-5.00")).toBe("-5.00");
    expect(signedMoney("0.00")).toBe("0.00");
  });
});

describe("AMOUNT_PATTERN", () => {
  it("accepts plain amounts with up to two decimals", () => {
    for (const ok of ["200", "200.0", "200.00", "0.5", "1720.25"]) expect(AMOUNT_PATTERN.test(ok)).toBe(true);
  });

  it("refuses anything else", () => {
    for (const bad of ["", "abc", "-5", "1,000", "200.123", ".5", "200.", "$200"]) {
      expect(AMOUNT_PATTERN.test(bad)).toBe(false);
    }
  });
});

describe("splitLine", () => {
  it("leaves a line with no quote as one plain piece", () => {
    const a = assessment();
    expect(splitLine("p1-L5", lineText(a, "p1-L5"), a.profile)).toEqual([{ text: "Dear Loss Mitigation Team,", key: null }]);
  });

  it("highlights the exact quote inside its line, with plain text around it", () => {
    const a = assessment();
    const pieces = splitLine("p1-L14", lineText(a, "p1-L14"), a.profile);
    expect(pieces.map((p) => p.key)).toEqual(["intent", null]);
    expect(pieces[0].text).toBe("I want to keep my home");
    expect(pieces.map((p) => p.text).join("")).toBe(lineText(a, "p1-L14")); // nothing lost or added
  });

  it("shows two quotes on the same line in the order they appear: reason, then onset", () => {
    const a = assessment();
    const pieces = splitLine("p1-L6", lineText(a, "p1-L6"), a.profile);
    expect(pieces.map((p) => p.text).join("")).toBe(lineText(a, "p1-L6"));
    // The onset quote ("in July") sits inside the reason quote, so the earlier one keeps the overlap.
    expect(pieces.filter((p) => p.key).map((p) => p.key)).toEqual(["primary_reason"]);
  });

  it("highlights the whole line when the quote is not found in it whole", () => {
    const a = assessment();
    const items: ProfileItem[] = [
      { ...a.profile[0], quote: { text: "a quote that runs over two lines", line_ids: ["p1-L7"] } },
    ];
    expect(splitLine("p1-L7", lineText(a, "p1-L7"), items)).toEqual([
      { text: lineText(a, "p1-L7"), key: "primary_reason" },
    ]);
  });

  it("ignores items with no quote", () => {
    const a = assessment();
    const items: ProfileItem[] = [{ ...a.profile[0], quote: null }];
    expect(splitLine("p1-L6", lineText(a, "p1-L6"), items)).toHaveLength(1);
  });
});

describe("reviewLabel", () => {
  it("says what state a profile item is in", () => {
    const item = assessment().profile[0];
    expect(reviewLabel(item)).toBe("Not reviewed");
    expect(reviewLabel({ ...item, review: { status: "confirmed", reason: null, by: "u", at: "x", original_label: "a" } })).toBe(
      "Reviewer-confirmed",
    );
    expect(reviewLabel({ ...item, review: { status: "corrected", reason: "r", by: "u", at: "x", original_label: "a" } })).toBe(
      "Reviewer-corrected",
    );
  });
});
