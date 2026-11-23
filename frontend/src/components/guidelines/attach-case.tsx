"use client";

import { SELECT_CLASS } from "@/components/documents/select-class";
import type { Case } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AttachCaseProps {
  cases: Case[];
  attached: boolean;
  caseId: string | null;
  onAttachedChange: (attached: boolean) => void;
  onCaseChange: (caseId: string) => void;
  disabled?: boolean;
}

/** "Attach case" adds a case's facts to the question, so the answer can list facts to check. Off by default. */
export function AttachCase({ cases, attached, caseId, onAttachedChange, onCaseChange, disabled }: AttachCaseProps) {
  const none = cases.length === 0;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={attached}
        aria-label="Attach case"
        disabled={disabled || none}
        onClick={() => onAttachedChange(!attached)}
        className={cn(
          "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50",
          attached ? "border-teal bg-teal/10 text-teal" : "text-navy hover:bg-accent",
        )}
      >
        <span
          aria-hidden
          className={cn("relative h-4 w-7 rounded-full transition-colors", attached ? "bg-teal" : "bg-neutral-chip/40")}
        >
          <span className={cn("absolute top-0.5 size-3 rounded-full bg-white transition-all", attached ? "left-3.5" : "left-0.5")} />
        </span>
        Attach case
      </button>
      {attached ? (
        <label className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
          Case
          <select className={SELECT_CLASS} value={caseId ?? ""} onChange={(e) => onCaseChange(e.target.value)} disabled={disabled}>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <span className="text-xs text-muted-foreground">
          {none ? "No case to attach." : "Adds the case's facts, so the answer can list what to check."}
        </span>
      )}
    </div>
  );
}
