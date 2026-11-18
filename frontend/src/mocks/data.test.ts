import { describe, expect, it } from "vitest";
import { listCases, listDocuments } from "@/lib/api";
import { ANGELA_CASE_ID, DANIEL_CASE_ID, mockCases, mockDocuments } from "./data";

describe("mock data", () => {
  it("every document belongs to a mock case", () => {
    const ids = new Set(mockCases.map((c) => c.id));
    for (const d of mockDocuments) expect(ids.has(d.case_id)).toBe(true);
  });

  it("each case's document_count matches its documents", () => {
    for (const c of mockCases) {
      const count = mockDocuments.filter((d) => d.case_id === c.id).length;
      expect(c.document_count).toBe(count);
    }
  });

  it("has one case per pillar", () => {
    expect(mockCases.map((c) => c.pillar).sort()).toEqual(["loss_mitigation", "underwriting"]);
  });

  it("uses unique IDs", () => {
    const ids = [...mockCases.map((c) => c.id), ...mockDocuments.map((d) => d.id)];
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("carries the pay stub net-pay flag from the demo story", () => {
    const stub = mockDocuments.find((d) => d.doc_type === "pay_stub" && d.case_id === DANIEL_CASE_ID);
    expect(stub?.status).toBe("needs_review");
    expect(stub?.flags[0].code).toBe("DI-CHK-02");
    expect(stub?.flags[0].evidence?.line_ids).toEqual(["p1-L31"]);
  });

  it("never uses decision wording (CLAUDE.md rule 3)", () => {
    const text = JSON.stringify([mockCases, mockDocuments]);
    expect(text).not.toMatch(/approv|deny|denied|offer|eligib|qualif/i);
  });
});

describe("api layer on mocks", () => {
  it("lists cases and filters by pillar", async () => {
    expect(await listCases()).toHaveLength(2);
    const lm = await listCases("loss_mitigation");
    expect(lm).toHaveLength(1);
    expect(lm[0].id).toBe(ANGELA_CASE_ID);
  });

  it("lists only the documents of the asked case", async () => {
    const docs = await listDocuments(DANIEL_CASE_ID);
    expect(docs.length).toBeGreaterThan(0);
    expect(docs.every((d) => d.case_id === DANIEL_CASE_ID)).toBe(true);
  });
});
