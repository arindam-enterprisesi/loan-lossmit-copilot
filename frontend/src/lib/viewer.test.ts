import { describe, expect, it } from "vitest";
import type { Field } from "@/lib/types";
import { boxesFromFields, boxStyle, clampPage, pageCountFor, stepZoom, ZOOM_STEPS } from "./viewer";

const field = (name: string, evidence: Field["evidence"]): Field => ({
  name,
  value: "v",
  original_value: "v",
  certainty: "high",
  flags: [],
  review_status: "unreviewed",
  version: 1,
  evidence,
});

const ev = (page: number, withBox: boolean) => ({
  document_id: "d",
  page,
  line_ids: [`p${page}-L01`],
  ...(withBox ? { bbox: { x0: 0.1, y0: 0.2, x1: 0.3, y1: 0.25 } } : {}),
});

describe("stepZoom", () => {
  it("moves one step up or down", () => {
    expect(stepZoom(1, 1)).toBe(1.5);
    expect(stepZoom(1, -1)).toBe(0.75);
  });

  it("stops at both ends", () => {
    expect(stepZoom(ZOOM_STEPS[0], -1)).toBe(0.5);
    expect(stepZoom(3, 1)).toBe(3);
  });

  it("snaps an in-between value to the nearest step first", () => {
    expect(stepZoom(1.4, 1)).toBe(2); // 1.4 is nearest to 1.5, so up is 2
  });
});

describe("clampPage", () => {
  it("keeps the page between 1 and the page count", () => {
    expect(clampPage(0, 3)).toBe(1);
    expect(clampPage(2, 3)).toBe(2);
    expect(clampPage(9, 3)).toBe(3);
  });

  it("never goes below page 1 even with a zero page count", () => {
    expect(clampPage(5, 0)).toBe(1);
  });
});

describe("boxStyle", () => {
  it("turns a 0 to 1 box into percentages", () => {
    const s = boxStyle({ x0: 0.242, y0: 0.4, x1: 0.311, y1: 0.41 });
    expect(parseFloat(String(s.left))).toBeCloseTo(24.2, 5);
    expect(parseFloat(String(s.top))).toBeCloseTo(40, 5);
    expect(parseFloat(String(s.width))).toBeCloseTo(6.9, 5);
    expect(parseFloat(String(s.height))).toBeCloseTo(1, 5);
  });
});

describe("boxesFromFields", () => {
  it("includes only fields that have a box, with a readable label and their page", () => {
    const boxes = boxesFromFields([
      field("net_pay_current", ev(1, true)),
      field("employer_name", ev(2, false)), // evidence but no box
      field("notes", null), // no evidence
    ]);
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).toMatchObject({ name: "net_pay_current", label: "Net pay current", page: 1 });
  });
});

describe("pageCountFor", () => {
  it("uses the document's page count", () => {
    expect(pageCountFor(3, [field("a", ev(1, true))])).toBe(3);
  });

  it("falls back to the highest page a field points to", () => {
    expect(pageCountFor(null, [field("a", ev(1, true)), field("b", ev(4, true))])).toBe(4);
  });

  it("is at least 1 for an empty document", () => {
    expect(pageCountFor(undefined, [])).toBe(1);
  });
});
