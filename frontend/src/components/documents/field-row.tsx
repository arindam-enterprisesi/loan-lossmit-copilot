"use client";

import { FlagChip, severityTone } from "@/components/shared/flag-chip";
import {
  CERTAINTY_LABEL,
  certaintyTone,
  fieldLabel,
  hasOpenFlags,
  REVIEW_STATUS_LABEL,
  REVIEW_STATUS_TONE,
} from "@/lib/documents";
import type { Field, FieldReview } from "@/lib/types";
import { cn } from "@/lib/utils";
import { FieldReviewForm } from "./field-review-form";

interface FieldRowProps {
  field: Field;
  selected: boolean;
  /** True while the matching box on the page is hovered, so the row lights up too. */
  highlighted?: boolean;
  onSelect: () => void;
  /** Called with true when the pointer enters the row and false when it leaves. */
  onHover?: (hovering: boolean) => void;
  onReview: (review: FieldReview) => Promise<boolean>;
  disabled?: boolean;
}

/** One extracted value: value, certainty, flags and review status. The selected row shows the review form. */
export function FieldRow({ field, selected, highlighted, onSelect, onHover, onReview, disabled }: FieldRowProps) {
  const changed = field.value !== field.original_value;
  const open = hasOpenFlags(field);

  return (
    <li
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      data-highlighted={highlighted ? "true" : undefined}
      className={cn(
        "rounded-lg border bg-card p-3 transition-colors",
        selected ? "border-teal ring-1 ring-teal/40" : "hover:border-teal/50",
        highlighted && !selected && "border-teal/70 bg-teal/5",
        open && !selected && !highlighted && "border-danger/40",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="block w-full text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {fieldLabel(field.name)}
            </div>
            <div className="mt-0.5 break-words text-base font-semibold text-navy">
              {field.value ?? "—"}
            </div>
            {changed ? (
              <div className="mt-0.5 text-xs text-muted-foreground">
                Originally read as <s>{field.original_value ?? "—"}</s>
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <FlagChip tone={REVIEW_STATUS_TONE[field.review_status]}>
              {REVIEW_STATUS_LABEL[field.review_status]}
            </FlagChip>
            <FlagChip tone={certaintyTone(field.certainty)}>{CERTAINTY_LABEL[field.certainty]}</FlagChip>
          </div>
        </div>
        {field.flags.length > 0 ? (
          <ul className="mt-2 space-y-1">
            {field.flags.map((f) => (
              <li key={f.code} className="flex items-start gap-2 text-sm">
                <FlagChip tone={severityTone(f.severity)}>{f.code}</FlagChip>
                <span className="text-navy">{f.message}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {field.review_reason ? (
          <div className="mt-2 text-xs text-muted-foreground">Reason: {field.review_reason}</div>
        ) : null}
      </button>
      {selected ? <FieldReviewForm key={field.version} field={field} onSubmit={onReview} disabled={disabled} /> : null}
    </li>
  );
}
