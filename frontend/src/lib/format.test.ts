import { describe, expect, it } from "vitest";
import { DOC_STATUS_LABEL, formatDate, formatMoney, humanize } from "./format";
import type { DocumentStatus } from "./types";

describe("humanize", () => {
  it("turns API codes into readable labels", () => {
    expect(humanize("pay_stub")).toBe("Pay stub");
    expect(humanize("mortgage_assistance_application")).toBe("Mortgage assistance application");
    expect(humanize("w2")).toBe("W2");
  });
});

describe("formatMoney", () => {
  it("adds thousands separators to the backend's text and keeps the decimals", () => {
    expect(formatMoney("5980.00")).toBe("5,980.00");
    expect(formatMoney("444.41")).toBe("444.41");
    expect(formatMoney("1234567.80")).toBe("1,234,567.80");
    expect(formatMoney("0.00")).toBe("0.00");
    expect(formatMoney("-280.00")).toBe("-280.00");
    expect(formatMoney("-1280.50")).toBe("-1,280.50");
  });

  it("never rounds or reformats: an amount with extra decimals is kept as is", () => {
    expect(formatMoney("5980.123456")).toBe("5,980.123456");
  });

  it("shows a dash for a missing amount and leaves non-amounts alone", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
    expect(formatMoney("")).toBe("—");
    expect(formatMoney("n/a")).toBe("n/a");
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
