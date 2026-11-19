"use client";

import { useState } from "react";
import { SignOffNote } from "@/components/shared/sign-off-note";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { buildReview, type ReviewAction } from "@/lib/field-review";
import type { Field, FieldReview } from "@/lib/types";

interface FieldReviewFormProps {
  field: Field;
  /** Sends the review. Resolves true when it was saved; the parent shows the message when it was not. */
  onSubmit: (review: FieldReview) => Promise<boolean>;
  disabled?: boolean;
}

/** Confirm, correct or reject one extracted value. The original value is kept by the server. */
export function FieldReviewForm({ field, onSubmit, disabled }: FieldReviewFormProps) {
  const [mode, setMode] = useState<Exclude<ReviewAction, "confirm"> | null>(null);
  const [value, setValue] = useState(field.value ?? "");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{ value?: string; reason?: string }>({});
  const [busy, setBusy] = useState(false);

  const send = async (action: ReviewAction) => {
    const result = buildReview(action, { value, reason }, field.version ?? 0);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      const saved = await onSubmit(result.review);
      if (saved) {
        setMode(null);
        setReason("");
      }
    } finally {
      setBusy(false);
    }
  };

  const locked = disabled || busy;

  return (
    <div className="mt-3 border-t pt-3">
      {mode === null ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => send("confirm")} disabled={locked}>
            Confirm value
          </Button>
          <Button size="sm" variant="outline" onClick={() => setMode("correct")} disabled={locked}>
            Correct
          </Button>
          <Button size="sm" variant="outline" onClick={() => setMode("reject")} disabled={locked}>
            Reject
          </Button>
          <SignOffNote className="ml-1" />
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            send(mode);
          }}
        >
          {mode === "correct" ? (
            <div>
              <label htmlFor={`value-${field.name}`} className="text-xs font-semibold text-muted-foreground">
                Corrected value
              </label>
              <Input
                id={`value-${field.name}`}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                aria-invalid={errors.value ? true : undefined}
                autoFocus
              />
              {errors.value ? <p className="mt-1 text-xs text-danger">{errors.value}</p> : null}
            </div>
          ) : null}
          <div>
            <label htmlFor={`reason-${field.name}`} className="text-xs font-semibold text-muted-foreground">
              {mode === "correct" ? "Why is the value being corrected?" : "Why is the value being rejected?"}
            </label>
            <Input
              id={`reason-${field.name}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-invalid={errors.reason ? true : undefined}
              maxLength={1000}
            />
            {errors.reason ? <p className="mt-1 text-xs text-danger">{errors.reason}</p> : null}
          </div>
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={locked}>
              {mode === "correct" ? "Save correction" : "Save rejection"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setMode(null);
                setErrors({});
              }}
              disabled={locked}
            >
              Cancel
            </Button>
            <SignOffNote />
          </div>
        </form>
      )}
    </div>
  );
}
