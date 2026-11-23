"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cleanReason, DOCUMENT_TYPES, docTypeLabel, TYPE_REASON_MAX } from "@/lib/documents";
import type { DocumentType } from "@/lib/types";
import { SELECT_CLASS } from "./select-class";

interface TypeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The document being typed, shown in the description. */
  fileName: string;
  /** The type it has now, if any. Shown preselected and changes the title to "Change". */
  currentType?: DocumentType | null;
  /**
   * Sends the chosen type and the optional reason (already trimmed, undefined when blank).
   * If it throws, the dialog stays open and shows the message.
   */
  onConfirm: (type: DocumentType, reason?: string) => Promise<void>;
}

/** Pick or change a document's type, with an optional reason that goes into the audit record. */
export function TypeDialog({ open, onOpenChange, fileName, currentType, onConfirm }: TypeDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* The form is only mounted while the dialog is open, so it starts fresh every time. */}
        <TypeForm
          fileName={fileName}
          currentType={currentType}
          onConfirm={onConfirm}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

interface TypeFormProps {
  fileName: string;
  currentType?: DocumentType | null;
  onConfirm: (type: DocumentType, reason?: string) => Promise<void>;
  onClose: () => void;
}

function TypeForm({ fileName, currentType, onConfirm, onClose }: TypeFormProps) {
  // "unrecognized" is not a choice, so a document with that type starts with nothing selected.
  const [type, setType] = useState<DocumentType | "">(
    currentType && DOCUMENT_TYPES.includes(currentType) ? currentType : "",
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!type) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(type, cleanReason(reason));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The type could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <DialogHeader>
        <DialogTitle>{currentType ? "Change document type" : "Choose document type"}</DialogTitle>
        <DialogDescription>
          {fileName}. Changing the type reads the document again. Your reason is kept in the audit record.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-1">
        <label htmlFor="type-dialog-type" className="text-xs font-semibold text-muted-foreground">
          Document type
        </label>
        <select
          id="type-dialog-type"
          className={SELECT_CLASS}
          value={type}
          onChange={(e) => setType(e.target.value as DocumentType | "")}
          disabled={busy}
        >
          <option value="">Choose a type</option>
          {DOCUMENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {docTypeLabel(t)}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-1">
        <label htmlFor="type-dialog-reason" className="text-xs font-semibold text-muted-foreground">
          Reason (optional)
        </label>
        <textarea
          id="type-dialog-reason"
          rows={3}
          maxLength={TYPE_REASON_MAX}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={busy}
          className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <span data-testid="reason-count" className="text-right text-xs tabular-nums text-muted-foreground">
          {reason.length}/{TYPE_REASON_MAX}
        </span>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" disabled={!type || busy}>
          Confirm type
        </Button>
      </DialogFooter>
    </form>
  );
}
