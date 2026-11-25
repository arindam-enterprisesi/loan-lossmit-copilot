"use client";

import { SOURCE_SETS } from "@/lib/guidelines";
import type { SourceSet } from "@/lib/guidelines-types";
import { cn } from "@/lib/utils";

interface SourceSetPickerProps {
  value: SourceSet;
  onChange: (value: SourceSet) => void;
  disabled?: boolean;
}

/** Which loaded sources a question may be answered from: Guidelines, Regulation X, or All. One is always chosen. */
export function SourceSetPicker({ value, onChange, disabled }: SourceSetPickerProps) {
  const move = (step: number) => {
    const at = SOURCE_SETS.findIndex((s) => s.value === value);
    onChange(SOURCE_SETS[(at + step + SOURCE_SETS.length) % SOURCE_SETS.length].value);
  };
  return (
    <div
      role="radiogroup"
      aria-label="Source set"
      className="inline-grid grid-cols-3 gap-1 rounded-lg bg-accent p-1"
      onKeyDown={(e) => {
        if (disabled) return;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          e.preventDefault();
          move(1);
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          e.preventDefault();
          move(-1);
        }
      }}
    >
      {SOURCE_SETS.map((s) => (
        <button
          key={s.value}
          type="button"
          role="radio"
          aria-checked={value === s.value}
          tabIndex={value === s.value ? 0 : -1}
          title={s.hint}
          disabled={disabled}
          onClick={() => onChange(s.value)}
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50",
            value === s.value ? "bg-teal text-white shadow-sm" : "text-navy hover:bg-white/70",
          )}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
