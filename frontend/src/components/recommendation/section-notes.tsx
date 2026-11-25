"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Annotation, AnnotationSection } from "@/lib/copilot-types";
import { ANNOTATION_MAX, ANNOTATION_SECTION_LABEL } from "@/lib/copilot";
import { formatDate } from "@/lib/format";

interface SectionNotesProps {
  section: AnnotationSection;
  /** The reviewer's notes on this part, oldest first. */
  notes: Annotation[];
  /** Adds a note. A failure is thrown, so the box can show it and keep what was typed. */
  onAdd: (section: AnnotationSection, text: string) => Promise<void>;
  /** False while there is no report to annotate yet. Existing notes still show. */
  canAdd?: boolean;
}

/**
 * The reviewer's notes on one part of the recommendation (Feature Design 8.2, step 5). A note is added beside
 * what the agents wrote and never changes it. It records what the reviewer thinks, and decides nothing.
 */
export function SectionNotes({ section, notes, onAdd, canAdd = true }: SectionNotesProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxId = useId();
  const label = ANNOTATION_SECTION_LABEL[section];

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onAdd(section, text.trim());
      setText("");
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The note could not be added.");
    } finally {
      setBusy(false);
    }
  };

  if (notes.length === 0 && !canAdd) return null;

  return (
    <div className="space-y-2" data-testid={`notes-${section}`}>
      {notes.length > 0 ? (
        <ul aria-label={`Notes on ${label}`} className="space-y-1.5">
          {notes.map((n) => (
            <li key={n.id} className="rounded-lg border-l-4 border-teal/60 bg-teal/5 px-3 py-2 text-sm text-navy">
              <p>{n.text}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Reviewer note · {n.by} · {formatDate(n.at)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}

      {open ? (
        <div className="grid gap-2">
          <label htmlFor={boxId} className="text-xs font-semibold text-muted-foreground">
            {`Note on ${label}`}
          </label>
          <textarea
            id={boxId}
            rows={2}
            maxLength={ANNOTATION_MAX}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
            className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
          />
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button size="sm" onClick={save} disabled={busy || !text.trim()}>
              Save note
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                setError(null);
                setText("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : canAdd ? (
        <Button size="sm" variant="outline" aria-label={`Add a note on ${label}`} onClick={() => setOpen(true)}>
          Add note
        </Button>
      ) : null}
    </div>
  );
}
