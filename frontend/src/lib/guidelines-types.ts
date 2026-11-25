// Types for the Guideline and Regulation Assistant (Feature Design section 5).
//
// PROPOSAL for the answer: contracts/openapi.yaml has no guideline endpoints yet, and the backend on
// `main` has only the read side (GET /guidelines/sources and GET /guidelines/passages/{id}, in
// backend/app/api/routers/guidelines.py). The ask endpoint (POST /guidelines/ask, Feature Design 5.7) is
// Arindam's and does not exist yet, so the shape of an answer here is my proposal to him. When he adds it,
// replace this file's answer types with types generated from the contract.
//
// The assistant answers only from retrieved passages: every sentence ends in a numbered citation marker,
// every marker opens a passage, and when no passage supports an answer the screen says so (never a guess).
// Nothing here decides anything: it lists provisions and facts to check, never that a borrower meets a requirement
// or that a servicer complied (CLAUDE.md rule 3).

/** Which loaded sources a question may be answered from. */
export type SourceSet = "guidelines" | "regulation_x" | "all";

/** "authoritative" has a version or "as of" date; "illustrative" is written for the demo. */
export type PassageLabel = "authoritative" | "illustrative";

export interface GuidelinePassage {
  id: string;
  source_id: string;
  /** The document, e.g. "Fannie Mae Selling Guide". */
  source_title: string;
  /** The section, e.g. "B3-3.1-01 Overtime and bonus income". */
  heading: string;
  text: string;
  label: PassageLabel;
  /** The page in the source document, when the source has pages. The backend does not send it yet. */
  page: number | null;
  /** The version or "as of" date of the source. The backend does not send it yet. */
  version: string | null;
  /** A warning about the passage, e.g. that it is a seeded sample and not the publisher's text. */
  notice: string | null;
}

export interface GuidelineSource {
  id: string;
  title: string;
  /** "agency_guide", "lender_overlay", "regulation", "investor_guide". */
  kind: string;
  label: PassageLabel;
  passage_count: number;
}

/** One short sentence of an answer, with the numbers of the citations that support it. */
export interface AnswerSentence {
  text: string;
  /** Marker numbers, in order. Every one is in the answer's `citations`. */
  citations: number[];
}

/** A numbered marker and the passage it opens. */
export interface AnswerCitation {
  marker: number;
  passage_id: string;
}

/** Passages from different sources on the same point, shown side by side (an agency guide against a lender overlay). */
export interface SourceComparison {
  topic: string;
  /** Marker numbers of the passages to show next to each other. */
  markers: number[];
}

export type AnswerStatus = "answered" | "no_support";

export interface GuidelineAnswer {
  id: string;
  question: string;
  source_set: SourceSet;
  /** The case whose facts were attached, or null. */
  case_id: string | null;
  asked_at: string;
  status: AnswerStatus;
  /** Empty when `status` is "no_support". */
  sentences: AnswerSentence[];
  citations: AnswerCitation[];
  /** The retrieved passages the citations point at. */
  passages: GuidelinePassage[];
  comparison: SourceComparison | null;
  /** With a case attached: facts to check against the provisions. Never a conclusion about the borrower. */
  facts_to_check: string[];
  /** "Not legal advice; confirm with your compliance team." on every Regulation X answer, else null. */
  notice: string | null;
  /** Sentences that failed the citation checks and were taken out. The screen says how many. */
  removed_sentences: number;
}

export type FeedbackRating = "helpful" | "not_helpful" | "wrongly_cited";

/** Body of POST /guidelines/answers/{id}/feedback. */
export interface GuidelineFeedback {
  rating: FeedbackRating;
  /** An optional note. */
  note?: string;
}
