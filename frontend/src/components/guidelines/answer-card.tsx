import { FlagChip } from "@/components/shared/flag-chip";
import { citationProblems, passageFor, REGULATION_X_NOTICE, sourceSetLabel, usesRegulationX } from "@/lib/guidelines";
import type { FeedbackRating, GuidelineAnswer } from "@/lib/guidelines-types";
import { formatDate } from "@/lib/format";
import { CitationMarker } from "./citation-marker";
import { FeedbackBar } from "./feedback-bar";
import { SourceComparison } from "./source-comparison";

interface AnswerCardProps {
  answer: GuidelineAnswer;
  /** The title of the attached case, when there is one. */
  caseTitle?: string;
  /** The rating already given, or null. */
  feedback: FeedbackRating | null;
  feedbackPending?: boolean;
  onOpenCitation: (marker: number) => void;
  onRate: (rating: FeedbackRating) => void;
}

/**
 * One answer: short sentences, each ending in numbered citation markers that open their passage. Where
 * sources differ they are shown side by side. When no passage supports an answer it says so and gives
 * no guess. A Regulation X answer carries the notice. With a case attached it lists facts to check,
 * never a conclusion about the borrower or the servicer.
 */
export function AnswerCard({ answer, caseTitle, feedback, feedbackPending, onOpenCitation, onRate }: AnswerCardProps) {
  const problems = answer.status === "answered" ? citationProblems(answer) : [];
  const notice = answer.notice ?? (usesRegulationX(answer) ? REGULATION_X_NOTICE : null);

  return (
    <article aria-label="Answer" data-testid={`answer-${answer.id}`} className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-semibold text-navy">Answer</span>
        <FlagChip tone="neutral">{sourceSetLabel(answer.source_set)}</FlagChip>
        {answer.case_id ? <FlagChip tone="info">Case attached{caseTitle ? `: ${caseTitle}` : ""}</FlagChip> : null}
        <span>{formatDate(answer.asked_at)}</span>
      </div>

      {answer.status === "no_support" ? (
        <div className="mt-3 rounded-lg border border-dashed bg-panel p-4" role="status">
          <p className="text-base font-semibold text-navy">No supporting passage found</p>
          <p className="mt-1 text-sm text-muted-foreground">
            The loaded sources do not answer this question, so no answer is given. Try the other source sets, or ask it another
            way.
          </p>
        </div>
      ) : problems.length > 0 ? (
        <p role="alert" className="mt-3 rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-navy">
          This answer could not be checked against its sources, so it is not shown.
        </p>
      ) : (
        <>
          <div className="mt-3 space-y-2">
            {answer.sentences.map((s, i) => (
              <p key={i} className="text-sm leading-relaxed text-navy">
                {s.text}
                {s.citations.map((m) => (
                  <CitationMarker key={m} marker={m} heading={passageFor(answer, m)?.heading} onOpen={onOpenCitation} />
                ))}
              </p>
            ))}
          </div>

          <SourceComparison answer={answer} onOpen={onOpenCitation} />

          {answer.facts_to_check.length > 0 ? (
            <section aria-label="Facts to check" className="mt-4 rounded-lg border bg-panel px-4 py-3">
              <h4 className="text-sm text-navy">Facts to check for this case</h4>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-navy">
                {answer.facts_to_check.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <p className="mt-1.5 text-xs text-muted-foreground">These are things to look at. They are not a conclusion about the borrower or the servicer.</p>
            </section>
          ) : null}

          {answer.removed_sentences > 0 ? (
            <p role="note" className="mt-3 text-xs text-muted-foreground">
              {answer.removed_sentences === 1
                ? "1 sentence was removed because its citation did not check out."
                : `${answer.removed_sentences} sentences were removed because their citations did not check out.`}
            </p>
          ) : null}
        </>
      )}

      {notice ? (
        <p role="note" className="mt-3 rounded-lg border border-gold/40 bg-gold/10 px-3 py-2 text-xs font-semibold text-navy">
          {notice}
        </p>
      ) : null}

      {answer.status === "answered" && problems.length === 0 ? (
        <div className="mt-4 border-t pt-3">
          <FeedbackBar value={feedback} pending={feedbackPending} onRate={onRate} />
        </div>
      ) : null}
    </article>
  );
}
