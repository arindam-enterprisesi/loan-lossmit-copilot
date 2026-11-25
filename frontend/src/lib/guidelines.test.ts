import { describe, expect, it } from "vitest";
import {
  citationProblems,
  EXAMPLE_QUESTIONS,
  FEEDBACK_LABEL,
  FEEDBACK_ORDER,
  passageFor,
  passageIdFor,
  REGULATION_X_NOTICE,
  SOURCE_SETS,
  sourceSetLabel,
  usesRegulationX,
} from "./guidelines";
import { toGuidelinePassage, toGuidelineSource } from "./guidelines-real";
import type { GuidelineAnswer } from "./guidelines-types";

const passage = (id: string, source_title = "Fannie Mae Selling Guide") => ({
  id,
  source_id: "s",
  source_title,
  heading: "B3-3.1-01 Overtime",
  text: "Overtime may be counted when it is likely to continue.",
  label: "authoritative" as const,
  page: 412,
  version: "2026-09-02",
  notice: null,
});

const answer = (over: Partial<GuidelineAnswer> = {}): GuidelineAnswer => ({
  id: "a1",
  question: "q",
  source_set: "guidelines",
  case_id: null,
  asked_at: "2026-11-23T09:00:00Z",
  status: "answered",
  sentences: [{ text: "S one.", citations: [1] }, { text: "S two.", citations: [1, 2] }],
  citations: [
    { marker: 1, passage_id: "p1" },
    { marker: 2, passage_id: "p2" },
  ],
  passages: [passage("p1"), passage("p2")],
  comparison: null,
  facts_to_check: [],
  notice: null,
  removed_sentences: 0,
  ...over,
});

describe("labels and lists", () => {
  it("has the three source sets in the order of the design", () => {
    expect(SOURCE_SETS.map((s) => s.label)).toEqual(["Guidelines", "Regulation X", "All"]);
    expect(sourceSetLabel("regulation_x")).toBe("Regulation X");
  });

  it("has the three feedback choices", () => {
    expect(FEEDBACK_ORDER.map((r) => FEEDBACK_LABEL[r])).toEqual(["Helpful", "Not helpful", "Wrongly cited"]);
  });

  it("has example questions, and the notice in the design's words", () => {
    expect(EXAMPLE_QUESTIONS.length).toBeGreaterThanOrEqual(3);
    expect(REGULATION_X_NOTICE).toBe("Not legal advice; confirm with your compliance team.");
  });
});

describe("passageFor and passageIdFor", () => {
  it("find the passage a marker opens", () => {
    expect(passageFor(answer(), 2)?.id).toBe("p2");
    expect(passageIdFor(answer(), 2)).toBe("p2");
  });

  it("say so when the marker is unknown, or the passage was not sent with the answer", () => {
    expect(passageFor(answer(), 9)).toBeUndefined();
    expect(passageIdFor(answer(), 9)).toBeUndefined();
    const lean = answer({ passages: [] });
    expect(passageFor(lean, 1)).toBeUndefined();
    expect(passageIdFor(lean, 1)).toBe("p1"); // still known, so it can be read by its ID
  });
});

describe("citationProblems: the checks the backend promises, repeated before an answer is trusted", () => {
  it("finds none in a good answer", () => {
    expect(citationProblems(answer())).toEqual([]);
  });

  it("finds a sentence with no citation", () => {
    expect(citationProblems(answer({ sentences: [{ text: "Unsupported.", citations: [] }] }))).toEqual(["Sentence 1 has no citation"]);
  });

  it("finds a marker that is not listed", () => {
    expect(citationProblems(answer({ sentences: [{ text: "S.", citations: [3] }] }))).toEqual(["Sentence 1 cites marker 3, which is not listed"]);
  });

  it("finds a citation whose passage was not retrieved", () => {
    expect(citationProblems(answer({ passages: [passage("p1")] }))).toEqual(["Citation 2 names a passage that was not retrieved"]);
  });
});

describe("usesRegulationX", () => {
  it("is true for the regulation's source set, or when a passage is from 12 CFR", () => {
    expect(usesRegulationX(answer({ source_set: "regulation_x" }))).toBe(true);
    expect(usesRegulationX(answer({ source_set: "all", passages: [passage("p1", "12 CFR 1024.41, loss mitigation procedures")] }))).toBe(true);
  });

  it("is false for guideline passages", () => {
    expect(usesRegulationX(answer({ source_set: "all" }))).toBe(false);
  });
});

describe("the real passage and source, translated", () => {
  it("reads a passage, and shows the page and version as not given because the backend does not send them", () => {
    const p = toGuidelinePassage({
      id: "sample-investor-a-v1.repayment-plan.1",
      source_id: "sample-investor-a-v1",
      source_title: "Sample Investor A servicing guide, version 1 (illustrative)",
      heading: "Repayment plan: hardship",
      text: "A repayment plan is considered only when the borrower's hardship has been confirmed as resolved.",
      label: "illustrative",
      notice: "Seeded sample: an invented illustrative passage, not an investor's real guide.",
    });
    expect(p).toMatchObject({ label: "illustrative", page: null, version: null, notice: expect.stringContaining("Seeded sample") });
  });

  it("shows any label other than authoritative as illustrative, the cautious reading", () => {
    const base = { id: "i", source_id: "s", source_title: "t", heading: "h", text: "x", notice: "" };
    expect(toGuidelinePassage({ ...base, label: "authoritative" }).label).toBe("authoritative");
    expect(toGuidelinePassage({ ...base, label: "draft" }).label).toBe("illustrative");
    expect(toGuidelinePassage({ ...base, label: "authoritative" }).notice).toBeNull(); // an empty notice is none
  });

  it("reads a source", () => {
    expect(toGuidelineSource({ id: "s", title: "T", kind: "regulation", label: "authoritative", passage_count: 4 })).toEqual({
      id: "s",
      title: "T",
      kind: "regulation",
      label: "authoritative",
      passage_count: 4,
    });
  });
});
