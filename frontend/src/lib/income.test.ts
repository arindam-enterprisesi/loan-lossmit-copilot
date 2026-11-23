import { describe, expect, it } from "vitest";
import { CANDIDATE_LABEL, documentHref, evidenceDetail, requestsText, workingEvidence } from "./income";

describe("evidenceDetail", () => {
  it("names the page and the line", () => {
    expect(evidenceDetail({ label: "Pay stub", page: 2, line_ids: ["p2-L7"] })).toBe("Page 2, line p2-L7");
  });

  it("says lines when there are several", () => {
    expect(evidenceDetail({ label: "x", page: 1, line_ids: ["p1-L1", "p1-L2"] })).toBe("Page 1, lines p1-L1, p1-L2");
  });

  it("is empty when the evidence names no page or line", () => {
    expect(evidenceDetail({ label: "W-2 2025, Box 5" })).toBe("");
  });
});

describe("documentHref", () => {
  it("points at the document's review screen under Document intelligence", () => {
    expect(documentHref("underwriting", "c1", "d1")).toBe("/underwriting/document-intelligence/c1/d1");
  });

  it("points Loss Mitigation documents at Document intake", () => {
    expect(documentHref("loss-mitigation", "c2", "d2")).toBe("/loss-mitigation/document-intake/c2/d2");
  });
});

describe("workingEvidence", () => {
  it("links evidence that has a document and leaves the rest as plain text", () => {
    const items = workingEvidence(
      [
        { label: "Pay stub", document_id: "d1", page: 1, line_ids: ["p1-L14"] },
        { label: "Income method income-method@1 (illustrative)" },
      ],
      "underwriting",
      "c1",
    );
    expect(items).toEqual([
      { label: "Pay stub", detail: "Page 1, line p1-L14", href: "/underwriting/document-intelligence/c1/d1" },
      { label: "Income method income-method@1 (illustrative)", detail: undefined, href: undefined },
    ]);
  });

  it("lists the same source once", () => {
    const e = { label: "Pay stub", document_id: "d1", page: 1, line_ids: ["p1-L14"] };
    expect(workingEvidence([e, { ...e }], "underwriting", "c1")).toHaveLength(1);
  });
});

describe("requestsText", () => {
  it("makes a short list ready to paste", () => {
    expect(requestsText(["A pay stub", "A letter"])).toBe(
      "Documents that would help settle the income flags:\n- A pay stub\n- A letter",
    );
  });

  it("is empty when there is nothing to request", () => {
    expect(requestsText([])).toBe("");
  });
});

describe("the candidate wording", () => {
  it("is exactly what the brief asks for and never claims a decision", () => {
    expect(CANDIDATE_LABEL).toBe("candidate - qualifying income is determined by the underwriter");
  });
});
