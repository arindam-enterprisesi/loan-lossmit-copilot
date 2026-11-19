"use client";

import { sortFlaggedFirst } from "@/lib/documents";
import type { Field, FieldReview } from "@/lib/types";
import { FieldRow } from "./field-row";

interface FieldListProps {
  fields: Field[];
  selectedName: string | null;
  onSelect: (name: string) => void;
  onReview: (fieldName: string, review: FieldReview) => Promise<boolean>;
  disabled?: boolean;
}

/** Extracted fields with open flags first. Selecting one lights up its box on the page. */
export function FieldList({ fields, selectedName, onSelect, onReview, disabled }: FieldListProps) {
  if (fields.length === 0) {
    return (
      <p className="rounded-lg border border-dashed bg-panel p-6 text-center text-sm text-muted-foreground">
        No fields were extracted from this document.
      </p>
    );
  }
  return (
    <ul className="space-y-3" aria-label="Extracted fields">
      {sortFlaggedFirst(fields).map((f) => (
        <FieldRow
          key={f.name}
          field={f}
          selected={f.name === selectedName}
          onSelect={() => onSelect(f.name)}
          onReview={(review) => onReview(f.name, review)}
          disabled={disabled}
        />
      ))}
    </ul>
  );
}
