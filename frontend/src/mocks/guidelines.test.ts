import { beforeEach, describe, expect, it } from "vitest";
import { citationProblems, REGULATION_X_NOTICE } from "@/lib/guidelines";
import type { SourceSet } from "@/lib/guidelines-types";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";
import { buildGuidelineAnswer, checkAsk, getMockPassage, mockSources, MOCK_PASSAGES } from "./guidelines";
import {
  askGuidelineMock,
  getGuidelinePassageMock,
  guidelineFeedbackMock,
  listGuidelineSourcesMock,
  resetMockStore,
  sendGuidelineFeedbackMock,
} from "./store";

const AT = "2026-11-23T09:00:00.000Z";
const ask = (question: string, source_set: SourceSet = "all", case_id: string | null = null) =>
  buildGuidelineAnswer({ question, source_set, case_id }, "g1", AT);

describe("the mock passages", () => {
  it("every passage is complete, has a unique ID, and says it is a demo excerpt", () => {
    expect(new Set(MOCK_PASSAGES.map((p) => p.id)).size).toBe(MOCK_PASSAGES.length);
    for (const p of MOCK_PASSAGES) {
      expect(p.text.length).toBeGreaterThan(40);
      expect(p.heading && p.source_title).toBeTruthy();
      expect(p.notice).toBe("Mock excerpt written for the demo, not the publisher's text.");
      expect(["authoritative", "illustrative"]).toContain(p.label);
    }
  });

  it("the agency guides and the regulation are authoritative, with a version; the lender overlay is illustrative", () => {
    const label = (source: string) => new Set(MOCK_PASSAGES.filter((p) => p.source_id === source).map((p) => p.label));
    expect(label("fannie-selling-guide")).toEqual(new Set(["authoritative"]));
    expect(label("reg-x-1024-41")).toEqual(new Set(["authoritative"]));
    expect(label("lender-overlay-demo")).toEqual(new Set(["illustrative"]));
    expect(MOCK_PASSAGES.every((p) => p.version)).toBe(true);
  });

  it("lists the four sources with their passage counts and kinds", () => {
    const sources = mockSources();
    expect(sources.map((s) => [s.id, s.kind, s.passage_count])).toEqual([
      ["fannie-selling-guide", "agency_guide", 2],
      ["freddie-seller-guide", "agency_guide", 2],
      ["lender-overlay-demo", "lender_overlay", 1],
      ["reg-x-1024-41", "regulation", 2],
    ]);
  });

  it("opens a passage by its ID, and a 404 for one that does not exist", () => {
    expect(getMockPassage("lender-overlay-demo.income-2-4.overtime").label).toBe("illustrative");
    expect(() => getMockPassage("nope")).toThrow(expect.objectContaining({ status: 404 }));
  });
});

describe("answers from the guideline sources", () => {
  it("overtime: cites Fannie Mae, Freddie Mac and the lender overlay, with the three side by side", () => {
    const a = ask("How is overtime income evaluated?");
    expect(a.status).toBe("answered");
    expect(a.sentences).toHaveLength(4);
    expect(a.citations.map((c) => c.passage_id)).toEqual([
      "fannie-selling-guide.b3-3-1-01.overtime",
      "freddie-seller-guide.5303-1.overtime",
      "lender-overlay-demo.income-2-4.overtime",
    ]);
    expect(a.comparison).toEqual({ topic: "How long the overtime history must be", markers: [1, 2, 3] });
    expect(a.notice).toBeNull();
  });

  it("every sentence cites something, and every marker names a retrieved passage (the checks the backend promises)", () => {
    for (const q of ["How is overtime income evaluated?", "What does the lender overlay say?", "How should a large deposit be documented?", "What does 1024.41 say about acknowledging an application?"]) {
      const a = ask(q);
      expect(a.status).toBe("answered");
      expect(citationProblems(a)).toEqual([]);
      expect(a.sentences.every((s) => s.citations.length > 0)).toBe(true);
    }
  });

  it("the lender overlay question puts the overlay beside the agency guide", () => {
    const a = ask("What does the lender overlay say about overtime?");
    expect(a.citations.map((c) => c.passage_id)).toEqual([
      "lender-overlay-demo.income-2-4.overtime",
      "fannie-selling-guide.b3-3-1-01.overtime",
    ]);
    expect(a.comparison?.markers).toEqual([1, 2]);
  });

  it("a large deposit question cites both guides, and shows that one sentence was removed", () => {
    const a = ask("How should a large deposit be documented?");
    expect(a.sentences[0].citations).toEqual([1, 2]);
    expect(a.removed_sentences).toBe(1);
    expect(a.comparison).toBeNull();
  });

  it("answers carry the question, source set, case, time and an ID", () => {
    expect(ask("How is overtime income evaluated?", "guidelines", DANIEL_CASE_ID)).toMatchObject({
      id: "g1",
      question: "How is overtime income evaluated?",
      source_set: "guidelines",
      case_id: DANIEL_CASE_ID,
      asked_at: AT,
    });
  });
});

describe("Regulation X answers", () => {
  it("cites 12 CFR 1024.41, in the regulation's own words (a mock excerpt), with the notice", () => {
    const a = ask("What must a servicer do after receiving a loss mitigation application?", "regulation_x");
    expect(a.status).toBe("answered");
    expect(a.citations.map((c) => c.passage_id)).toEqual(["reg-x-1024-41.b-2.acknowledgement", "reg-x-1024-41.c-1.evaluation"]);
    expect(a.notice).toBe(REGULATION_X_NOTICE);
    expect(a.notice).toBe("Not legal advice; confirm with your compliance team.");
  });

  it("carries the notice under All too, and not on a guidelines answer", () => {
    expect(ask("What does 1024.41 say about an application?", "all").notice).toBe(REGULATION_X_NOTICE);
    expect(ask("How is overtime income evaluated?", "all").notice).toBeNull();
  });
});

describe("case-aware answers: facts to check, never a conclusion", () => {
  it("with Angela's case attached, lists the facts to check for a missing document", () => {
    const a = ask("What must a servicer do about a missing document in a received application?", "regulation_x", ANGELA_CASE_ID);
    expect(a.facts_to_check).toEqual([
      "The date the loss mitigation application was received",
      "Which statement is missing (the August bank statement)",
      "Whether the written acknowledgement was sent, and when",
    ]);
  });

  it("with Daniel's case attached, lists the facts to check about his overtime history", () => {
    const a = ask("How is overtime income evaluated?", "guidelines", DANIEL_CASE_ID);
    expect(a.facts_to_check).toHaveLength(2);
    expect(a.facts_to_check[0]).toContain("2026 only");
  });

  it("without a case, or with a case that has nothing known for the topic, lists none", () => {
    expect(ask("How is overtime income evaluated?", "guidelines", null).facts_to_check).toEqual([]);
    expect(ask("How is overtime income evaluated?", "guidelines", ANGELA_CASE_ID).facts_to_check).toEqual([]);
  });

  it("never says a borrower qualifies or a servicer complied", () => {
    const wording = /\b(qualif|eligib|approv|denied|complied|in compliance)\b/i;
    for (const [q, set, c] of [
      ["How is overtime income evaluated?", "all", DANIEL_CASE_ID],
      ["What must a servicer do after receiving a loss mitigation application?", "regulation_x", ANGELA_CASE_ID],
      ["How should a large deposit be documented?", "guidelines", DANIEL_CASE_ID],
    ] as const) {
      const a = ask(q, set, c);
      const text = [...a.sentences.map((s) => s.text), ...a.facts_to_check, ...a.passages.map((p) => p.text)].join(" ");
      expect(text).not.toMatch(wording);
    }
  });
});

describe("no supporting passage found", () => {
  it("a question the sources do not cover gets no sentences and no citations, not a guess", () => {
    const a = ask("What are the jumbo loan limits?");
    expect(a).toMatchObject({ status: "no_support", sentences: [], citations: [], passages: [], comparison: null, facts_to_check: [] });
  });

  it("a topic is answered only from a source set that includes it", () => {
    expect(ask("How is overtime income evaluated?", "regulation_x").status).toBe("no_support");
    expect(ask("What must a servicer do after receiving a loss mitigation application?", "guidelines").status).toBe("no_support");
    expect(ask("How is overtime income evaluated?", "guidelines").status).toBe("answered");
  });

  it("a Regulation X search that finds nothing still carries the notice", () => {
    expect(ask("How is overtime income evaluated?", "regulation_x").notice).toBe(REGULATION_X_NOTICE);
    expect(ask("How is overtime income evaluated?", "guidelines").status).toBe("answered");
    expect(ask("What are the jumbo loan limits?", "all").notice).toBeNull();
  });
});

describe("what the mock refuses (422)", () => {
  it("a blank question, a question that is too long, and an unknown source set", () => {
    const refused = (question: string, set: SourceSet = "all") => expect(() => checkAsk({ question, source_set: set, case_id: null }));
    refused("").toThrow(expect.objectContaining({ status: 422, message: "Ask a question" }));
    refused("   ").toThrow(expect.objectContaining({ status: 422 }));
    refused("x".repeat(1001)).toThrow(expect.objectContaining({ status: 422 }));
    refused("ok", "nothing" as never).toThrow(expect.objectContaining({ status: 422 }));
  });

  it("trims the question", () => {
    expect(checkAsk({ question: "  hello  ", source_set: "all", case_id: null }).question).toBe("hello");
  });
});

describe("the mock store: ask, read, feedback", () => {
  beforeEach(() => resetMockStore());

  it("answers, and gives each answer its own ID", () => {
    const a = askGuidelineMock({ question: "How is overtime income evaluated?", source_set: "all", case_id: null });
    const b = askGuidelineMock({ question: "How is overtime income evaluated?", source_set: "all", case_id: null });
    expect(a.id).not.toBe(b.id);
    expect(a.status).toBe("answered");
  });

  it("lists the sources and opens a passage", () => {
    expect(listGuidelineSourcesMock()).toHaveLength(4);
    expect(getGuidelinePassageMock("fannie-selling-guide.b3-4-2-02.large-deposits").heading).toBe("B3-4.2-02 Large deposits");
  });

  it("records feedback on an answer, and the latest rating stands", () => {
    const a = askGuidelineMock({ question: "How is overtime income evaluated?", source_set: "all", case_id: null });
    sendGuidelineFeedbackMock(a.id, { rating: "helpful" });
    expect(guidelineFeedbackMock(a.id)).toEqual({ rating: "helpful" });
    sendGuidelineFeedbackMock(a.id, { rating: "wrongly_cited", note: "  Marker 2 is the wrong section  " });
    expect(guidelineFeedbackMock(a.id)).toEqual({ rating: "wrongly_cited", note: "Marker 2 is the wrong section" });
  });

  it("refuses feedback on an unknown answer (404) and an unknown rating (422)", () => {
    const a = askGuidelineMock({ question: "How is overtime income evaluated?", source_set: "all", case_id: null });
    expect(() => sendGuidelineFeedbackMock("nope", { rating: "helpful" })).toThrow(expect.objectContaining({ status: 404 }));
    expect(() => sendGuidelineFeedbackMock(a.id, { rating: "great" as never })).toThrow(expect.objectContaining({ status: 422 }));
  });

  it("forgets everything on reset", () => {
    const a = askGuidelineMock({ question: "How is overtime income evaluated?", source_set: "all", case_id: null });
    sendGuidelineFeedbackMock(a.id, { rating: "helpful" });
    resetMockStore();
    expect(guidelineFeedbackMock(a.id)).toBeUndefined();
    expect(() => sendGuidelineFeedbackMock(a.id, { rating: "helpful" })).toThrow(expect.objectContaining({ status: 404 }));
  });
});
