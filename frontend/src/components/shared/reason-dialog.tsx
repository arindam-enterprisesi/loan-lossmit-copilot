"use client";

import { useId, useState } from "react";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/** An extra value the change needs next to the reason, such as the corrected value or an amount. */
export interface ReasonField {
  label: string;
  /** What the box starts with. */
  initialValue: string;
  /** When given, the value is picked from this list instead of typed. */
  options?: { value: string; label: string }[];
  /** Returns a message when the typed value is not acceptable, or null when it is. */
  validate?: (value: string) => string | null;
}

interface ReasonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** What will happen, in one or two sentences. */
  description: string;
  /** What the system said before this change, so the person sees what they are changing. */
  note?: string;
  /** The text on the confirm button, for example "Exclude from candidate". */
  confirmLabel: string;
  maxLength: number;
  /** An extra value to collect next to the reason. */
  field?: ReasonField;
  /**
   * Sends the trimmed reason and, when there is a field, its trimmed value. If it throws, the dialog
   * stays open, shows the message and keeps what was typed, so nothing is lost.
   */
  onConfirm: (reason: string, value: string) => Promise<void>;
}

/**
 * A change that needs a written reason before it can be made: include or exclude an income
 * component, override a checklist item, correct a hardship reading, adjust a budget item. The reason
 * is required (blank spaces do not count) and goes into the audit record next to what the system said.
 */
export function ReasonDialog({ open, onOpenChange, ...form }: ReasonDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Mounted only while open, so the boxes start fresh every time. */}
        <ReasonForm {...form} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

type ReasonFormProps = Omit<ReasonDialogProps, "open" | "onOpenChange"> & { onClose: () => void };

function ReasonForm({
  title,
  description,
  note,
  confirmLabel,
  maxLength,
  field,
  onConfirm,
  onClose,
}: ReasonFormProps) {
  const [reason, setReason] = useState("");
  const [value, setValue] = useState(field?.initialValue ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxId = useId();
  const fieldId = useId();
  const trimmed = reason.trim();
  const trimmedValue = value.trim();
  const fieldError = field?.validate && trimmedValue ? field.validate(trimmedValue) : null;
  const ready = trimmed !== "" && (!field || (trimmedValue !== "" && !fieldError));

  const submit = async () => {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(trimmed, trimmedValue);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The change could not be saved.");
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
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>

      {note ? <p className="rounded-lg bg-panel px-3 py-2 text-xs text-muted-foreground">{note}</p> : null}

      {field ? (
        <div className="grid gap-1">
          <label htmlFor={fieldId} className="text-xs font-semibold text-muted-foreground">
            {field.label}
          </label>
          {field.options ? (
            <select
              id={fieldId}
              className={SELECT_CLASS}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              disabled={busy}
            >
              {field.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : (
            <Input id={fieldId} value={value} onChange={(e) => setValue(e.target.value)} disabled={busy} />
          )}
          {fieldError ? (
            <p role="status" className="text-xs text-danger">
              {fieldError}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-1">
        <label htmlFor={boxId} className="text-xs font-semibold text-muted-foreground">
          Reason (required)
        </label>
        <textarea
          id={boxId}
          rows={3}
          maxLength={maxLength}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={busy}
          className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <span data-testid="reason-count" className="text-right text-xs tabular-nums text-muted-foreground">
          {reason.length}/{maxLength}
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
        <Button type="submit" disabled={!ready || busy}>
          {confirmLabel}
        </Button>
      </DialogFooter>
    </form>
  );
}
