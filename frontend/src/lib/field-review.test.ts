import { describe, expect, it } from "vitest";
import { buildReview } from "./field-review";

describe("buildReview", () => {
  it("confirm needs nothing but still carries the version", () => {
    expect(buildReview("confirm", {}, 3)).toEqual({
      ok: true,
      review: { action: "confirm", expected_version: 3 },
    });
  });

  it("correct needs a value and a reason", () => {
    const result = buildReview("correct", { value: "  ", reason: "" }, 1);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.value).toBeTruthy();
      expect(result.errors.reason).toBeTruthy();
    }
  });

  it("builds a correct body with trimmed text", () => {
    expect(buildReview("correct", { value: " 2033.61 ", reason: " OCR misread " }, 1)).toEqual({
      ok: true,
      review: { action: "correct", value: "2033.61", reason: "OCR misread", expected_version: 1 },
    });
  });

  it("reject needs a reason but no value", () => {
    const missing = buildReview("reject", { value: "ignored" }, 2);
    expect(missing.ok).toBe(false);
    const ok = buildReview("reject", { value: "ignored", reason: "Not on the page" }, 2);
    expect(ok).toEqual({
      ok: true,
      review: { action: "reject", reason: "Not on the page", expected_version: 2 },
    });
  });
});
