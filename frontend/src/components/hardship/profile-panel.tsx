"use client";

import { useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { HARDSHIP_REASON_MAX, reviewLabel } from "@/lib/hardship";
import type { ProfileItem, ProfileKey } from "@/lib/hardship-types";
import { cn } from "@/lib/utils";

interface ProfilePanelProps {
  items: ProfileItem[];
  selectedKey: ProfileKey | null;
  /** Shows the item's quote strongly in the letter. */
  onSelect: (key: ProfileKey) => void;
  onConfirm: (key: ProfileKey) => void;
  /**
   * Sends a correction. If it throws, the window stays open and shows the message, so nothing typed
   * is lost.
   */
  onCorrect: (key: ProfileKey, value: string, reason: string) => Promise<void>;
}

const reviewTone = (item: ProfileItem) =>
  !item.review ? "neutral" : item.review.status === "confirmed" ? "success" : "info";

/**
 * What the letter was read as: reason, onset, duration and intent, each with its quote and a tick
 * when the quote was checked in code. The specialist confirms or corrects each one. Corrections keep
 * the original reading and need a reason.
 */
export function ProfilePanel({ items, selectedKey, onSelect, onConfirm, onCorrect }: ProfilePanelProps) {
  const [correcting, setCorrecting] = useState<ProfileItem | null>(null);

  return (
    <section aria-labelledby="profile-heading" className="space-y-3">
      <h3 id="profile-heading" className="text-base text-navy">
        Hardship profile
      </h3>
      {items.map((item) => (
        <article
          key={item.key}
          aria-label={item.label}
          className={cn("rounded-xl border bg-card p-4", item.key === selectedKey && "ring-2 ring-gold/60")}
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="text-xs font-semibold text-muted-foreground">{item.label}</div>
              <div className="text-base font-semibold text-navy">{item.value_label}</div>
            </div>
            <FlagChip tone={reviewTone(item)}>{reviewLabel(item)}</FlagChip>
          </div>

          {item.quote ? (
            <figure className="mt-2">
              <blockquote className="border-l-2 border-gold pl-3 text-sm text-navy">“{item.quote.text}”</blockquote>
              <figcaption className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>Letter, {item.quote.line_ids.length > 1 ? "lines" : "line"} {item.quote.line_ids.join(", ")}</span>
                {item.quote_verified ? (
                  <FlagChip tone="success">✓ Quote verified</FlagChip>
                ) : (
                  <FlagChip tone="danger">Quote not verified</FlagChip>
                )}
              </figcaption>
            </figure>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">No quote for this item.</p>
          )}

          {item.review ? (
            <div className="mt-2 space-y-0.5 rounded-lg bg-panel px-3 py-2 text-xs text-muted-foreground">
              <div>
                {item.review.status === "confirmed" ? "Confirmed" : "Corrected"} by {item.review.by},{" "}
                {formatDate(item.review.at)}
              </div>
              {item.review.status === "corrected" ? (
                <>
                  <div>Reason: {item.review.reason}</div>
                  <div>Read from the letter: {item.review.original_label}</div>
                </>
              ) : null}
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="ghost"
              size="sm"
              aria-pressed={item.key === selectedKey}
              aria-label={`Show ${item.label} in the letter`}
              onClick={() => onSelect(item.key)}
            >
              Show in letter
            </Button>
            {!item.review ? (
              <Button size="sm" aria-label={`Confirm ${item.label}`} onClick={() => onConfirm(item.key)}>
                Confirm
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              aria-label={`Correct ${item.label}`}
              onClick={() => setCorrecting(item)}
            >
              Correct
            </Button>
          </div>
        </article>
      ))}

      <ReasonDialog
        open={correcting !== null}
        onOpenChange={(open) => {
          if (!open) setCorrecting(null);
        }}
        title={correcting ? `Correct ${correcting.label}` : ""}
        description="Your correction replaces the value that is used from here on. The letter reading is kept beside it, with your reason."
        note={
          correcting
            ? `The letter reading says: ${correcting.value_label}${correcting.quote ? ` (“${correcting.quote.text}”)` : ""}`
            : undefined
        }
        confirmLabel="Save correction"
        maxLength={HARDSHIP_REASON_MAX}
        field={
          correcting
            ? {
                label: correcting.options ? "Correct value" : `Correct ${correcting.label.toLowerCase()}`,
                initialValue: correcting.options ? correcting.value : correcting.value_label,
                options: correcting.options ?? undefined,
              }
            : undefined
        }
        onConfirm={(reason, value) => onCorrect(correcting!.key, value, reason)}
      />
    </section>
  );
}
