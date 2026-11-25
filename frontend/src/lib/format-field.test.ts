import { describe, expect, it } from "vitest";
import { formatFieldValue } from "./format";

describe("formatFieldValue", () => {
  it("adds thousands separators to an amount with two decimals", () => {
    expect(formatFieldValue("2083.61")).toBe("2,083.61");
    expect(formatFieldValue("5980.00")).toBe("5,980.00");
    expect(formatFieldValue("1234567.89")).toBe("1,234,567.89");
  });

  it("keeps the sign, and leaves a small amount alone", () => {
    expect(formatFieldValue("-1200.50")).toBe("-1,200.50");
    expect(formatFieldValue("34.50")).toBe("34.50");
  });

  it("does not touch a year, an account number or a count, which have no decimals", () => {
    expect(formatFieldValue("2026")).toBe("2026");
    expect(formatFieldValue("123456789")).toBe("123456789");
    expect(formatFieldValue("26")).toBe("26");
  });

  it("does not touch text, dates or a value with other than two decimals", () => {
    expect(formatFieldValue("Northwind Logistics")).toBe("Northwind Logistics");
    expect(formatFieldValue("2026-10-15")).toBe("2026-10-15");
    expect(formatFieldValue("41.2")).toBe("41.2");
    expect(formatFieldValue("0.409524")).toBe("0.409524");
  });

  it("shows a dash for nothing", () => {
    expect(formatFieldValue(null)).toBe("—");
    expect(formatFieldValue(undefined)).toBe("—");
    expect(formatFieldValue("")).toBe("—");
  });
});
