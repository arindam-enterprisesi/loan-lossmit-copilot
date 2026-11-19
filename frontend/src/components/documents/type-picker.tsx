"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { DOCUMENT_TYPES, docTypeLabel } from "@/lib/documents";
import type { DocumentType } from "@/lib/types";
import { SELECT_CLASS } from "./select-class";

interface TypePickerProps {
  /** Called with the chosen type when the user confirms it. */
  onConfirm: (type: DocumentType) => void | Promise<void>;
  disabled?: boolean;
}

/** Choose a type for a document the system could not classify (status "type_needed"). */
export function TypePicker({ onConfirm, disabled }: TypePickerProps) {
  const [type, setType] = useState<DocumentType | "">("");
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    if (!type) return;
    setBusy(true);
    try {
      await onConfirm(type);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="Document type"
        className={SELECT_CLASS}
        value={type}
        onChange={(e) => setType(e.target.value as DocumentType | "")}
        disabled={disabled || busy}
      >
        <option value="">Choose a type</option>
        {DOCUMENT_TYPES.map((t) => (
          <option key={t} value={t}>
            {docTypeLabel(t)}
          </option>
        ))}
      </select>
      <Button size="sm" onClick={confirm} disabled={!type || disabled || busy}>
        Set type
      </Button>
    </div>
  );
}
