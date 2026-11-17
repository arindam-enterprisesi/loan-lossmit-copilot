import { describe, expect, it } from "vitest";
import { DOC_STATUS_LABEL, formatDate, humanize } from "./format";
import type { DocumentStatus } from "./types";

describe("humanize", () => {
  it("turns API codes into readable labels", () => {
    expect(humanize("pay_stub")).toBe("Pay stub");
    expect(humanize("mortgage_assistance_application")).toBe("Mortgage assistance application");
    expect(humanize("w2")).toBe("W2");
  });
});

describe("formatDate", () => {
  it("formats an ISO date", () => {
    expect(formatDate("2026-11-02")).toBe("2 Nov 2026");
  });

  it("formats an ISO date-time in UTC, so server and browser agree", () => {
    expect(formatDate("2026-11-02T23:30:00Z")).toBe("2 Nov 2026");
  });

  it("shows a dash when there is no date", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
  });
});

describe("DOC_STATUS_LABEL", () => {
  it("has a label for every status in the contract", () => {
    const statuses: DocumentStatus[] = [
      "uploaded",
      "processing",
      "type_needed",
      "needs_review",
      "reviewed",
      "failed",
    ];
    for (const s of statuses) expect(DOC_STATUS_LABEL[s]).toBeTruthy();
  });
});
