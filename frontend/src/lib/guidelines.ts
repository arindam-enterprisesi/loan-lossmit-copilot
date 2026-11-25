// Small display helpers for the Guideline and Regulation Assistant. No answering happens here: the
// backend retrieves the passages and writes the cited answer, and these only turn it into things to show.
import type {
  AnswerCitation,
  FeedbackRating,
  GuidelineAnswer,
  GuidelinePassage,
  PassageLabel,
  SourceSet,
} from "./guidelines-types";

/** The notice every Regulation X answer carries (Feature Design 5.2). */
export const REGULATION_X_NOTICE = "Not legal advice; confirm with your compliance team.";

/** The longest question the screen sends. */
export const QUESTION_MAX = 1000;

export const SOURCE_SETS: { value: SourceSet; label: string; hint: string }[] = [
  { value: "guidelines", label: "Guidelines", hint: "Agency and lender guides" },
  { value: "regulation_x", label: "Regulation X", hint: "12 CFR Part 1024, Subpart C" },
  { value: "all", label: "All", hint: "Every loaded source" },
];

export const sourceSetLabel = (value: SourceSet): string => SOURCE_SETS.find((s) => s.value === value)?.label ?? value;

export const LABEL_TEXT: Record<PassageLabel, string> = {
  authoritative: "Authoritative",
  illustrative: "Illustrative",
};

export const FEEDBACK_LABEL: Record<FeedbackRating, string> = {
  helpful: "Helpful",
  not_helpful: "Not helpful",
  wrongly_cited: "Wrongly cited",
};

export const FEEDBACK_ORDER: FeedbackRating[] = ["helpful", "not_helpful", "wrongly_cited"];

/** Example questions shown before the first one is asked. */
export const EXAMPLE_QUESTIONS = [
  "How is overtime income evaluated?",
  "What does the lender overlay say about overtime?",
  "How should a large deposit be documented?",
  "What must a servicer do after receiving a loss mitigation application?",
];

/** The passage a marker opens, from the answer's own retrieved passages. */
export function passageFor(answer: GuidelineAnswer, marker: number): GuidelinePassage | undefined {
  const citation = answer.citations.find((c) => c.marker === marker);
  return citation ? answer.passages.find((p) => p.id === citation.passage_id) : undefined;
}

/** The passage ID a marker points at, even if the passage itself was not sent with the answer. */
export const passageIdFor = (answer: GuidelineAnswer, marker: number): string | undefined =>
  answer.citations.find((c) => c.marker === marker)?.passage_id;

/**
 * Checks what the backend promised: every marker used by a sentence is one of the citations, and every
 * citation names a retrieved passage. A failure here means an answer the screen should not trust.
 */
export function citationProblems(answer: GuidelineAnswer): string[] {
  const problems: string[] = [];
  const markers = new Set(answer.citations.map((c) => c.marker));
  const passageIds = new Set(answer.passages.map((p) => p.id));
  for (const [i, s] of answer.sentences.entries()) {
    if (s.citations.length === 0) problems.push(`Sentence ${i + 1} has no citation`);
    for (const m of s.citations) if (!markers.has(m)) problems.push(`Sentence ${i + 1} cites marker ${m}, which is not listed`);
  }
  for (const c of answer.citations as AnswerCitation[]) {
    if (!passageIds.has(c.passage_id)) problems.push(`Citation ${c.marker} names a passage that was not retrieved`);
  }
  return problems;
}

/** True when an answer draws on Regulation X, so the notice must be shown. */
export const usesRegulationX = (answer: GuidelineAnswer): boolean =>
  answer.source_set === "regulation_x" || answer.passages.some((p) => /\b(12 CFR|Regulation X)\b/i.test(p.source_title));
