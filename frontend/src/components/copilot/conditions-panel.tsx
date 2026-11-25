"use client";

import { useId, useState } from "react";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { FlagChip } from "@/components/shared/flag-chip";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { useToast } from "@/components/shared/toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { Condition, ConditionAddRequest, ConditionDecisionRequest, Priority } from "@/lib/copilot-types";
import {
  CONDITION_TEXT_MAX,
  DECISION_LABEL,
  DECISION_TONE,
  PRIORITY_LABEL,
  PRIORITY_ORDER,
  PRIORITY_TONE,
  REASON_MAX,
} from "@/lib/copilot";
import { formatDate } from "@/lib/format";

interface ConditionsPanelProps {
  conditions: Condition[];
  /** Accepts, edits or rejects one. A failure is thrown, so the window or the toast can show it. */
  onDecide: (id: string, req: ConditionDecisionRequest) => Promise<void>;
  onAdd: (req: ConditionAddRequest) => Promise<void>;
}

type Dialogue = { kind: "edit" | "reject"; condition: Condition } | null;

/**
 * The suggested conditions. Each can be accepted, edited or rejected; an edit and a rejection need a written
 * reason. What the agents wrote is never changed: an edit sits beside it, and a rejected condition stays on the
 * list with its reason. A reviewer can add their own. None of this is a decision about the loan.
 */
export function ConditionsPanel({ conditions, onDecide, onAdd }: ConditionsPanelProps) {
  const toast = useToast();
  const [dialog, setDialog] = useState<Dialogue>(null);
  const [adding, setAdding] = useState(false);

  const accept = async (c: Condition) => {
    try {
      await onDecide(c.id, { decision: "accepted" });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not accept the condition.", { retry: () => accept(c) });
    }
  };

  return (
    <section aria-labelledby="conditions-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="conditions-heading" className="text-lg">
          Suggested conditions
        </h2>
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          Add condition
        </Button>
      </div>

      {conditions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No conditions suggested. You can add your own.</p>
      ) : (
        <ol className="space-y-3">
          {conditions.map((c) => (
            <li key={c.id} data-testid={`condition-${c.id}`} data-decision={c.decision} className="space-y-2 rounded-xl border bg-card p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold tabular-nums text-muted-foreground">{c.position}.</span>
                <FlagChip tone={PRIORITY_TONE[c.priority]}>{PRIORITY_LABEL[c.priority]}</FlagChip>
                <FlagChip tone={DECISION_TONE[c.decision]}>{DECISION_LABEL[c.decision]}</FlagChip>
                {c.source === "user" ? <FlagChip tone="neutral">Added by a reviewer</FlagChip> : null}
              </div>

              <p className="text-sm text-navy">{c.current_text}</p>

              {c.decision === "edited" ? (
                <p className="rounded-lg bg-panel px-3 py-2 text-xs text-muted-foreground">
                  <span className="font-semibold">Written by the agents:</span> {c.text}
                </p>
              ) : null}
              {c.reason ? <p className="text-xs text-muted-foreground">Reason: {c.reason}</p> : null}
              {c.decided_by && c.decision !== "pending" ? (
                <p className="text-xs text-muted-foreground">
                  {DECISION_LABEL[c.decision]} by {c.decided_by}
                  {c.decided_at ? ` on ${formatDate(c.decided_at)}` : ""}
                </p>
              ) : null}

              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" aria-label={`Accept condition ${c.position}`} disabled={c.decision === "accepted"} onClick={() => accept(c)}>
                  Accept
                </Button>
                <Button size="sm" variant="outline" aria-label={`Edit condition ${c.position}`} onClick={() => setDialog({ kind: "edit", condition: c })}>
                  Edit
                </Button>
                <Button size="sm" variant="outline" aria-label={`Reject condition ${c.position}`} disabled={c.decision === "rejected"} onClick={() => setDialog({ kind: "reject", condition: c })}>
                  Reject
                </Button>
              </div>
            </li>
          ))}
        </ol>
      )}

      {dialog ? (
        <ReasonDialog
          open
          onOpenChange={(open) => {
            if (!open) setDialog(null);
          }}
          title={dialog.kind === "edit" ? `Edit condition ${dialog.condition.position}` : `Reject condition ${dialog.condition.position}`}
          description={
            dialog.kind === "edit"
              ? "Write the condition as you want it. What the agents wrote stays beside your version."
              : "The condition stays on the list as rejected, with your reason."
          }
          note={`The agents wrote: ${dialog.condition.text}`}
          confirmLabel={dialog.kind === "edit" ? "Save edit" : "Reject condition"}
          maxLength={REASON_MAX}
          field={
            dialog.kind === "edit"
              ? {
                  label: "Condition text",
                  initialValue: dialog.condition.current_text,
                  validate: (v) => (v.length > CONDITION_TEXT_MAX ? `Keep it to ${CONDITION_TEXT_MAX} characters.` : null),
                }
              : undefined
          }
          onConfirm={(reason, value) =>
            onDecide(dialog.condition.id, dialog.kind === "edit" ? { decision: "edited", edited_text: value, reason } : { decision: "rejected", reason })
          }
        />
      ) : null}

      <AddConditionDialog open={adding} onOpenChange={setAdding} onAdd={onAdd} />
    </section>
  );
}

interface AddConditionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (req: ConditionAddRequest) => Promise<void>;
}

function AddConditionDialog({ open, onOpenChange, onAdd }: AddConditionDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Mounted only while open, so the boxes start fresh every time. */}
        <AddConditionForm onAdd={onAdd} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function AddConditionForm({ onAdd, onClose }: { onAdd: (req: ConditionAddRequest) => Promise<void>; onClose: () => void }) {
  const [text, setText] = useState("");
  const [priority, setPriority] = useState<Priority>("attention");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textId = useId();
  const priorityId = useId();
  const trimmed = text.trim();

  const submit = async () => {
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd({ text: trimmed, priority });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The condition could not be added.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <DialogHeader>
        <DialogTitle>Add a condition</DialogTitle>
        <DialogDescription>Your own condition goes on the list beside the suggested ones. The review record shows who added it.</DialogDescription>
      </DialogHeader>
      <div className="grid gap-1">
        <label htmlFor={textId} className="text-xs font-semibold text-muted-foreground">
          Condition
        </label>
        <textarea
          id={textId}
          rows={3}
          maxLength={CONDITION_TEXT_MAX}
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
          className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>
      <div className="grid gap-1">
        <label htmlFor={priorityId} className="text-xs font-semibold text-muted-foreground">
          Priority
        </label>
        <select id={priorityId} className={SELECT_CLASS} value={priority} onChange={(e) => setPriority(e.target.value as Priority)} disabled={busy}>
          {PRIORITY_ORDER.map((p) => (
            <option key={p} value={p}>
              {PRIORITY_LABEL[p]}
            </option>
          ))}
        </select>
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
        <Button type="submit" disabled={!trimmed || busy}>
          Add condition
        </Button>
      </DialogFooter>
    </form>
  );
}
