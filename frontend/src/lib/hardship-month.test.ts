import { describe, expect, it } from "vitest";
import { monthLabel, ONSET_PATTERN } from "./hardship";

describe("the onset month", () => {
  it("accepts a month written YYYY-MM and nothing else", () => {
    for (const ok of ["2026-07", "2026-01", "2026-12", "1999-09"]) expect(ONSET_PATTERN.test(ok)).toBe(true);
    for (const bad of ["July 2026", "2026-13", "2026-00", "2026-6", "26-06", "2026-07-01", " 2026-07", ""]) {
      expect(ONSET_PATTERN.test(bad)).toBe(false);
    }
  });

  it("shows a month by name", () => {
    expect(monthLabel("2026-07")).toBe("July 2026");
    expect(monthLabel("2026-01")).toBe("January 2026");
    expect(monthLabel("2025-12")).toBe("December 2025");
  });

  it("shows anything that is not a month as it came", () => {
    expect(monthLabel("last summer")).toBe("last summer");
    expect(monthLabel("2026-13")).toBe("2026-13");
    expect(monthLabel("")).toBe("");
  });
});
