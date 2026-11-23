"use client";

import { Button } from "@/components/ui/button";
import { FEEDBACK_LABEL, FEEDBACK_ORDER } from "@/lib/guidelines";
import type { FeedbackRating } from "@/lib/guidelines-types";

interface FeedbackBarProps {
  /** The rating already given to this answer, or null. */
  value: FeedbackRating | null;
  /** A rating is being sent. */
  pending?: boolean;
  onRate: (rating: FeedbackRating) => void;
}

/** Helpful, not helpful or wrongly cited. The latest choice stands, and is shown as chosen. */
export function FeedbackBar({ value, pending, onRate }: FeedbackBarProps) {
  return (
    <div role="group" aria-label="Feedback on this answer" className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted-foreground">Was this answer useful?</span>
      {FEEDBACK_ORDER.map((rating) => (
        <Button
          key={rating}
          size="sm"
          variant={value === rating ? "default" : "outline"}
          aria-pressed={value === rating}
          disabled={pending}
          onClick={() => {
            if (value !== rating) onRate(rating);
          }}
        >
          {FEEDBACK_LABEL[rating]}
        </Button>
      ))}
      {value ? (
        <span role="status" className="text-xs text-muted-foreground">
          Recorded: {FEEDBACK_LABEL[value]}
        </span>
      ) : null}
    </div>
  );
}
