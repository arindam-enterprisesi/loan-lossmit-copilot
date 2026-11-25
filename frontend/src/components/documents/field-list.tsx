"use client";

import { EmptyState } from "@/components/shared/empty-state";
import { sortFlaggedFirst } from "@/lib/documents";
import type { Field, FieldReview } from "@/lib/types";
import { FieldRow } from "./field-row";

interface FieldListProps {
  fields: Field[];
  selectedName: string | null;
  /** The field whose box on the page is under the pointer, if any. */
  hoveredName?: string | null;
  onSelect: (name: string) => void;
  /** Called with a field name when the pointer enters its row, and null when it leaves. */
  onHover?: (name: string | null) => void;
  onReview: (fieldName: string, review: FieldReview) => Promise<boolean>;
  disabled?: boolean;
}

/** Extracted fields with open flags first. Selecting one lights up its box on the page. */
export function FieldList({
  fields,
  selectedName,
  hoveredName = null,
  onSelect,
  onHover,
  onReview,
  disabled,
}: FieldListProps) {
  if (fields.length === 0) {
    return <EmptyState>No fields were extracted from this document.</EmptyState>;
  }
  return (
    <ul className="space-y-3" aria-label="Extracted fields">
      {sortFlaggedFirst(fields).map((f) => (
        <FieldRow
          key={f.name}
          field={f}
          selected={f.name === selectedName}
          highlighted={f.name === hoveredName}
          onSelect={() => onSelect(f.name)}
          onHover={(hovering) => onHover?.(hovering ? f.name : null)}
          onReview={(review) => onReview(f.name, review)}
          disabled={disabled}
        />
      ))}
    </ul>
  );
}
