"use client";

import { MessageSquare, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/shared/empty-state";
import { useToast } from "@/components/shared/toast";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { askGuideline, sendGuidelineFeedback } from "@/lib/api";
import { EXAMPLE_QUESTIONS, passageFor, passageIdFor, QUESTION_MAX } from "@/lib/guidelines";
import type { FeedbackRating, GuidelineAnswer, SourceSet } from "@/lib/guidelines-types";
import type { Case } from "@/lib/types";
import { AnswerCard } from "./answer-card";
import { AttachCase } from "./attach-case";
import { PassagePanel } from "./passage-panel";
import { SourceSetPicker } from "./source-set-picker";

interface GuidelineWorkspaceProps {
  cases: Case[];
  /** The source set the picker starts on: Regulation X questions come from Loss Mitigation. */
  defaultSourceSet?: SourceSet;
}

interface Exchange {
  answer: GuidelineAnswer;
  feedback: FeedbackRating | null;
}

const messageOf = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);

/**
 * The Guideline and Regulation Assistant: a chat panel. Pick the source set, optionally attach a case,
 * ask a question, and read short sentences that each end in a numbered citation. A citation opens its
 * passage in a side panel. Where sources differ they are side by side; when nothing supports an answer it
 * says so. Every answer can be marked helpful, not helpful or wrongly cited.
 */
export function GuidelineWorkspace({ cases, defaultSourceSet = "all" }: GuidelineWorkspaceProps) {
  const toast = useToast();
  const [sourceSet, setSourceSet] = useState<SourceSet>(defaultSourceSet);
  const [attached, setAttached] = useState(false);
  const [caseId, setCaseId] = useState<string | null>(cases[0]?.id ?? null);
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  // The question being answered right now, shown as a placeholder.
  const [pending, setPending] = useState<string | null>(null);
  const [ratingFor, setRatingFor] = useState<string | null>(null);
  const [open, setOpen] = useState<{ answerId: string; marker: number } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Keep the newest answer in view.
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [exchanges.length, pending]);

  const ask = async (text: string) => {
    const clean = text.trim();
    if (!clean || clean.length > QUESTION_MAX || pending !== null) return;
    setPending(clean);
    try {
      const answer = await askGuideline(clean, sourceSet, attached ? caseId : null);
      setExchanges((current) => [...current, { answer, feedback: null }]);
      setQuestion("");
    } catch (e) {
      // The question stays in the box, so "Try again" sends the same one.
      toast.error(messageOf(e, "The question could not be answered."), { retry: () => ask(clean) });
    } finally {
      setPending(null);
    }
  };

  const rate = async (answerId: string, rating: FeedbackRating) => {
    setRatingFor(answerId);
    try {
      await sendGuidelineFeedback(answerId, rating);
      setExchanges((current) => current.map((x) => (x.answer.id === answerId ? { ...x, feedback: rating } : x)));
    } catch (e) {
      toast.error(messageOf(e, "The feedback could not be saved."), { retry: () => rate(answerId, rating) });
    } finally {
      setRatingFor(null);
    }
  };

  const openAnswer = open ? exchanges.find((x) => x.answer.id === open.answerId)?.answer : undefined;
  const titleOf = (id: string | null) => cases.find((c) => c.id === id)?.title;
  const tooLong = question.trim().length > QUESTION_MAX;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4">
        <SourceSetPicker value={sourceSet} onChange={setSourceSet} disabled={pending !== null} />
        <AttachCase
          cases={cases}
          attached={attached}
          caseId={caseId}
          onAttachedChange={setAttached}
          onCaseChange={setCaseId}
          disabled={pending !== null}
        />
      </div>

      <section aria-label="Conversation" className="flex flex-col gap-4">
        {exchanges.length === 0 && pending === null ? (
          <EmptyState title="Ask about the loaded sources">
            Answers come only from the loaded guides and regulation, and every sentence cites the passage it rests on. If the sources are
            silent, you will be told so.
          </EmptyState>
        ) : null}

        {exchanges.map(({ answer, feedback }) => (
          <div key={answer.id} className="flex flex-col gap-2">
            <div className="flex justify-end">
              <p className="max-w-xl rounded-2xl rounded-br-sm bg-teal px-4 py-2 text-sm text-white">{answer.question}</p>
            </div>
            <AnswerCard
              answer={answer}
              caseTitle={titleOf(answer.case_id)}
              feedback={feedback}
              feedbackPending={ratingFor === answer.id}
              onOpenCitation={(marker) => setOpen({ answerId: answer.id, marker })}
              onRate={(rating) => void rate(answer.id, rating)}
            />
          </div>
        ))}

        {pending !== null ? (
          <div className="flex flex-col gap-2">
            <div className="flex justify-end">
              <p className="max-w-xl rounded-2xl rounded-br-sm bg-teal px-4 py-2 text-sm text-white">{pending}</p>
            </div>
            <div role="status" aria-label="Looking for passages" className="space-y-2 rounded-xl border bg-card p-4">
              <span className="sr-only">Looking for passages…</span>
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/5" />
            </div>
          </div>
        ) : null}
        <div ref={endRef} />
      </section>

      {exchanges.length === 0 && pending === null ? (
        <div className="flex flex-wrap gap-2" aria-label="Example questions" role="group">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => void ask(q)}
              className="rounded-full border px-3 py-1.5 text-left text-xs text-navy transition-colors hover:bg-accent"
            >
              {q}
            </button>
          ))}
        </div>
      ) : null}

      <form
        aria-label="Ask a question"
        className="flex flex-col gap-2 rounded-xl border bg-card p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
      >
        <label htmlFor="guideline-question" className="text-xs font-semibold text-muted-foreground">
          Your question
        </label>
        <textarea
          id="guideline-question"
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends; Shift+Enter makes a new line.
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(question);
            }
          }}
          placeholder="For example: how is overtime income evaluated?"
          aria-invalid={tooLong ? true : undefined}
          className="w-full resize-none rounded-lg border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {tooLong ? <span className="text-danger">A question can be at most {QUESTION_MAX} characters.</span> : <span>Enter to ask, Shift+Enter for a new line.</span>}
            {exchanges.length > 0 ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => setExchanges([])} disabled={pending !== null}>
                <Trash2 className="size-3.5" />
                New conversation
              </Button>
            ) : null}
          </div>
          <Button type="submit" disabled={!question.trim() || tooLong || pending !== null}>
            <MessageSquare className="size-4" />
            {pending !== null ? "Asking…" : "Ask"}
          </Button>
        </div>
      </form>

      <PassagePanel
        open={open !== null}
        onOpenChange={(next) => {
          if (!next) setOpen(null);
        }}
        passageId={openAnswer && open ? (passageIdFor(openAnswer, open.marker) ?? null) : null}
        passage={openAnswer && open ? passageFor(openAnswer, open.marker) : undefined}
      />
    </div>
  );
}
