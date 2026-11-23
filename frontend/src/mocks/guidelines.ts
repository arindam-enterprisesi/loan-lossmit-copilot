// Mock Guideline and Regulation Assistant, shaped like the screen's own types (src/lib/guidelines-types.ts).
//
// The real engine is Arindam's (Feature Design 5): it retrieves passages and has a model write a cited
// answer. This mock stands in for it so every state of the screen can be shown: an answer with
// citations, passages that differ side by side, a Regulation X answer with its notice, a case-aware
// list of facts to check, a removed sentence, and "no supporting passage found". It matches the question
// to a few topics by keywords and builds each answer from a fixed, written-by-hand passage set. It does
// no retrieval and no reasoning.
//
// The passages are written for the demo (each carries a notice saying so): they are NOT the publishers'
// text, even where a source is labelled authoritative, which is how the real, loaded sources will be
// labelled.
import { ApiError } from "@/lib/api-error";
import { QUESTION_MAX, REGULATION_X_NOTICE } from "@/lib/guidelines";
import type {
  AnswerCitation,
  AnswerSentence,
  GuidelineAnswer,
  GuidelinePassage,
  GuidelineSource,
  SourceComparison,
  SourceSet,
} from "@/lib/guidelines-types";
import { ANGELA_CASE_ID, DANIEL_CASE_ID } from "./data";

const MOCK_NOTICE = "Mock excerpt written for the demo, not the publisher's text.";

const passage = (p: Omit<GuidelinePassage, "notice">): GuidelinePassage => ({ ...p, notice: MOCK_NOTICE });

export const MOCK_PASSAGES: GuidelinePassage[] = [
  passage({
    id: "fannie-selling-guide.b3-3-1-01.overtime",
    source_id: "fannie-selling-guide",
    source_title: "Fannie Mae Selling Guide",
    heading: "B3-3.1-01 Overtime and bonus income",
    text: "Overtime and bonus income may be counted when the borrower has received it for at least two years and it is likely to continue. A shorter history needs the reasons documented.",
    label: "authoritative",
    page: 412,
    version: "2026-09-02",
  }),
  passage({
    id: "freddie-seller-guide.5303-1.overtime",
    source_id: "freddie-seller-guide",
    source_title: "Freddie Mac Single-Family Seller/Servicer Guide",
    heading: "5303.1 Overtime, bonus and commission income",
    text: "Overtime, bonus and commission income may be counted with a history of at least one year when the employer confirms it is likely to continue. The amounts received are averaged over the period.",
    label: "authoritative",
    page: 187,
    version: "2026-08-12",
  }),
  passage({
    id: "lender-overlay-demo.income-2-4.overtime",
    source_id: "lender-overlay-demo",
    source_title: "Lender overlay (demo)",
    heading: "Overlay 2.4 Overtime and bonus",
    text: "Overtime and bonus income is counted only with a two-year history and an employer letter stating that it will continue.",
    label: "illustrative",
    page: 3,
    version: "v1",
  }),
  passage({
    id: "fannie-selling-guide.b3-4-2-02.large-deposits",
    source_id: "fannie-selling-guide",
    source_title: "Fannie Mae Selling Guide",
    heading: "B3-4.2-02 Large deposits",
    text: "A large deposit that is not explained by the borrower's regular income, or by a transfer between the borrower's own accounts, needs its source documented before the funds are counted.",
    label: "authoritative",
    page: 521,
    version: "2026-09-02",
  }),
  passage({
    id: "freddie-seller-guide.5501-3.large-deposits",
    source_id: "freddie-seller-guide",
    source_title: "Freddie Mac Single-Family Seller/Servicer Guide",
    heading: "5501.3 Deposits and the source of funds",
    text: "Deposits that are not from payroll or a transfer between the borrower's own accounts are reviewed. The source is documented with a statement or a letter when it cannot be traced.",
    label: "authoritative",
    page: 240,
    version: "2026-08-12",
  }),
  passage({
    id: "reg-x-1024-41.b-2.acknowledgement",
    source_id: "reg-x-1024-41",
    source_title: "12 CFR 1024.41, loss mitigation procedures",
    heading: "1024.41(b)(2) Acknowledgement of a loss mitigation application",
    text: "Within five days after receiving a loss mitigation application (not counting weekends and legal public holidays), a servicer must tell the borrower in writing that it received the application and whether the application is complete. If it is not complete, the notice says which documents or information are missing.",
    label: "authoritative",
    page: null,
    version: "as of 2026-09-01",
  }),
  passage({
    id: "reg-x-1024-41.c-1.evaluation",
    source_id: "reg-x-1024-41",
    source_title: "12 CFR 1024.41, loss mitigation procedures",
    heading: "1024.41(c)(1) Evaluation of a complete application",
    text: "If a loss mitigation application is complete, the servicer evaluates it within thirty days for all the loss mitigation options available to the borrower.",
    label: "authoritative",
    page: null,
    version: "as of 2026-09-01",
  }),
];

const byId = new Map(MOCK_PASSAGES.map((p) => [p.id, p]));
const pick = (id: string): GuidelinePassage => byId.get(id)!;

// The rules of the sample investor the Loss Mitigation recommendation applies (backend/app/db/demo/
// guideline_passages.json). Each rule in the waterfall cites one, and its passage opens from the card.
// They are read by ID only: the assistant does not search them, so its list of sources does not change.
const INVESTOR_NOTICE = "Illustrative: not an actual investor's requirements.";
const investor = (id: string, heading: string, text: string): GuidelinePassage => ({
  id: `sample-investor-a-v1.${id}`,
  source_id: "sample-investor-a-v1",
  source_title: "Sample Investor A guide",
  heading,
  text,
  label: "illustrative",
  page: null,
  version: "1",
  notice: INVESTOR_NOTICE,
});

export const INVESTOR_PASSAGES: GuidelinePassage[] = [
  investor(
    "order.1",
    "Order of options",
    "Options are evaluated in a fixed order: repayment plan, forbearance, payment deferral, loan modification, short sale, then deed in lieu. The evaluation stops at the first option whose conditions are met. Short sale and deed in lieu are evaluated only when no earlier option's conditions are met.",
  ),
  investor("repayment-plan.1", "Repayment plan: hardship", "A repayment plan is considered only when the borrower's hardship has been confirmed as resolved."),
  investor(
    "repayment-plan.2",
    "Repayment plan: surplus",
    "The borrower's documented monthly surplus must be at least the arrears divided by six, so the arrears can be repaid in six months.",
  ),
  investor("forbearance.1", "Forbearance: hardship", "Forbearance is considered only when the borrower's hardship has been confirmed as temporary."),
  investor("payment-deferral.1", "Payment deferral: hardship", "A payment deferral is considered only when the borrower's hardship has been confirmed as resolved."),
  investor("payment-deferral.2", "Payment deferral: surplus", "The borrower's documented monthly surplus at the contractual payment must be zero or more."),
  investor("payment-deferral.3", "Payment deferral: delinquency", "The loan must be six or fewer months delinquent."),
  investor(
    "loan-modification.1",
    "Loan modification: hardship",
    "A loan modification is considered only when the borrower's hardship has been confirmed as long-term or its duration is unknown.",
  ),
  investor("loan-modification.2", "Loan modification: intent", "The borrower must have confirmed that they intend to keep the home."),
  investor(
    "loan-modification.3",
    "Loan modification: target payment",
    "The target payment is 35% of the borrower's documented gross monthly income. It must be below the current contractual payment.",
  ),
];
const investorById = new Map(INVESTOR_PASSAGES.map((p) => [p.id, p]));

/** GET /guidelines/sources: every loaded source with how many passages it has. */
export function mockSources(): GuidelineSource[] {
  const kinds: Record<string, string> = {
    "fannie-selling-guide": "agency_guide",
    "freddie-seller-guide": "agency_guide",
    "lender-overlay-demo": "lender_overlay",
    "reg-x-1024-41": "regulation",
  };
  const seen = new Map<string, GuidelineSource>();
  for (const p of MOCK_PASSAGES) {
    const found = seen.get(p.source_id);
    if (found) found.passage_count += 1;
    else seen.set(p.source_id, { id: p.source_id, title: p.source_title, kind: kinds[p.source_id], label: p.label, passage_count: 1 });
  }
  return [...seen.values()];
}

/** GET /guidelines/passages/{id}: one passage, 404 if there is none with that ID. */
export function getMockPassage(id: string): GuidelinePassage {
  const found = byId.get(id) ?? investorById.get(id);
  if (!found) throw new ApiError(404, "Passage not found");
  return structuredClone(found);
}

// ---- The topics the mock can answer -------------------------------------------------------------

interface Draft {
  /** The passages cited, in marker order: the first is marker 1. */
  passages: GuidelinePassage[];
  sentences: { text: string; citations: number[] }[];
  comparison: { topic: string; markers: number[] } | null;
  facts: Partial<Record<string, string[]>>;
  removed: number;
}

type Family = "guidelines" | "regulation_x";

interface Topic {
  family: Family;
  matches: RegExp;
  draft: () => Draft;
}

// The first topic that matches wins, so the narrower ones come first.
const TOPICS: Topic[] = [
  {
    family: "guidelines",
    matches: /overlay/i,
    draft: () => ({
      passages: [pick("lender-overlay-demo.income-2-4.overtime"), pick("fannie-selling-guide.b3-3-1-01.overtime")],
      sentences: [
        { text: "The lender overlay counts overtime and bonus income only with a two-year history and an employer letter that it will continue.", citations: [1] },
        { text: "The Fannie Mae guide asks for two years as well, and for the reasons to be documented when the history is shorter.", citations: [2] },
      ],
      comparison: { topic: "Overtime and bonus income: agency guide and lender overlay", markers: [1, 2] },
      facts: {},
      removed: 0,
    }),
  },
  {
    family: "guidelines",
    matches: /overtime|bonus/i,
    draft: () => ({
      passages: [
        pick("fannie-selling-guide.b3-3-1-01.overtime"),
        pick("freddie-seller-guide.5303-1.overtime"),
        pick("lender-overlay-demo.income-2-4.overtime"),
      ],
      sentences: [
        { text: "Overtime and bonus income may be counted when it is likely to continue.", citations: [1, 2] },
        { text: "Fannie Mae asks for a two-year history, and for the reasons to be documented when it is shorter.", citations: [1] },
        { text: "Freddie Mac can accept a one-year history when the employer confirms it is likely to continue.", citations: [2] },
        { text: "The lender overlay counts it only with a two-year history and an employer letter.", citations: [3] },
      ],
      comparison: { topic: "How long the overtime history must be", markers: [1, 2, 3] },
      facts: {
        [DANIEL_CASE_ID]: [
          "How many months of overtime and bonus the pay stubs and W-2s cover (the documented history covers 2026 only)",
          "Whether the employer confirms in writing that the overtime will continue",
        ],
      },
      removed: 0,
    }),
  },
  {
    family: "guidelines",
    matches: /deposit|sourced|source of funds|gift/i,
    draft: () => ({
      passages: [pick("fannie-selling-guide.b3-4-2-02.large-deposits"), pick("freddie-seller-guide.5501-3.large-deposits")],
      sentences: [
        { text: "A large deposit that is not regular income or a transfer between the borrower's own accounts needs its source documented.", citations: [1, 2] },
        { text: "Fannie Mae asks for the source to be documented before the funds are counted.", citations: [1] },
      ],
      comparison: null,
      facts: {
        [DANIEL_CASE_ID]: ["Where the 2,000.00 transfer on 2026-09-22 came from, and whether a statement or letter documents it"],
      },
      // The engine dropped one more sentence because its quotation was not an exact piece of its passage.
      removed: 1,
    }),
  },
  {
    family: "regulation_x",
    matches: /1024|regulation x|reg x|acknowledg|loss mitigation application|missing (document|statement)|complete application|within \d+ days/i,
    draft: () => ({
      passages: [pick("reg-x-1024-41.b-2.acknowledgement"), pick("reg-x-1024-41.c-1.evaluation")],
      sentences: [
        { text: "A servicer must acknowledge a loss mitigation application in writing within five days of receiving it, not counting weekends and legal public holidays.", citations: [1] },
        { text: "The acknowledgement says whether the application is complete and, if it is not, which documents or information are missing.", citations: [1] },
        { text: "A complete application is evaluated within thirty days.", citations: [2] },
      ],
      comparison: null,
      facts: {
        [ANGELA_CASE_ID]: [
          "The date the loss mitigation application was received",
          "Which statement is missing (the August bank statement)",
          "Whether the written acknowledgement was sent, and when",
        ],
      },
      removed: 0,
    }),
  },
];

/** What the mock does with a question: which topic it is, if any. */
export const topicOf = (question: string): Topic | undefined => TOPICS.find((t) => t.matches.test(question));

export interface AskInput {
  question: string;
  source_set: SourceSet;
  case_id: string | null;
}

/** POST /guidelines/ask: the 422 answers the backend would give for a bad request. */
export function checkAsk(input: AskInput): AskInput {
  const question = input.question?.trim() ?? "";
  if (!question) throw new ApiError(422, "Ask a question");
  if (question.length > QUESTION_MAX) throw new ApiError(422, `A question can be at most ${QUESTION_MAX} characters`);
  if (!["guidelines", "regulation_x", "all"].includes(input.source_set)) throw new ApiError(422, "Choose a source set");
  return { question, source_set: input.source_set, case_id: input.case_id };
}

/**
 * The answer to a question. A topic is answered only from a source set that includes it (a Regulation X
 * topic needs Regulation X or All); otherwise, or when no topic matches, the answer is "no supporting
 * passage found": no guess, and no sentences. Regulation X answers carry the notice. With a case
 * attached and facts known for it, the answer lists facts to check, never a conclusion.
 */
export function buildGuidelineAnswer(input: AskInput, id: string, at: string): GuidelineAnswer {
  const { question, source_set, case_id } = checkAsk(input);
  const base = { id, question, source_set, case_id, asked_at: at };
  const topic = topicOf(question);
  const allowed = topic && (source_set === "all" || source_set === topic.family);
  const notice = source_set === "regulation_x" || topic?.family === "regulation_x" ? REGULATION_X_NOTICE : null;

  if (!topic || !allowed) {
    return { ...base, status: "no_support", sentences: [], citations: [], passages: [], comparison: null, facts_to_check: [], notice: source_set === "regulation_x" ? REGULATION_X_NOTICE : null, removed_sentences: 0 };
  }

  const draft = topic.draft();
  const citations: AnswerCitation[] = draft.passages.map((p, i) => ({ marker: i + 1, passage_id: p.id }));
  const sentences: AnswerSentence[] = draft.sentences.map((s) => ({ text: s.text, citations: [...s.citations] }));
  const comparison: SourceComparison | null = draft.comparison ? { topic: draft.comparison.topic, markers: [...draft.comparison.markers] } : null;
  return {
    ...base,
    status: "answered",
    sentences,
    citations,
    passages: structuredClone(draft.passages),
    comparison,
    facts_to_check: case_id ? [...(draft.facts[case_id] ?? [])] : [],
    notice,
    removed_sentences: draft.removed,
  };
}
