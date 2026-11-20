"use client";

import { ReasonDialog } from "@/components/shared/reason-dialog";
import { formatMoney } from "@/lib/format";
import { INCOME_REASON_MAX } from "@/lib/income";
import type { IncomeComponent } from "@/lib/income-types";

interface IncomeDecisionDialogProps {
  /** The component being decided on. The dialog is closed while this is null. */
  component: IncomeComponent | null;
  onOpenChange: (open: boolean) => void;
  /**
   * Sends the decision with the trimmed reason. If it throws, the dialog stays open and shows the
   * message, so nothing is lost.
   */
  onConfirm: (included: boolean, reason: string) => Promise<void>;
}

/** Include or exclude one income component. A reason is required and goes into the audit record. */
export function IncomeDecisionDialog({ component, onOpenChange, onConfirm }: IncomeDecisionDialogProps) {
  // The button only gives the opposite of what is shown now.
  const include = component ? !component.included : false;
  const amount = component ? formatMoney(component.monthly.value) : "";
  return (
    <ReasonDialog
      open={component !== null}
      onOpenChange={onOpenChange}
      title={component ? `${include ? "Include" : "Exclude"} ${component.label}` : ""}
      description={
        component
          ? `${component.label}, ${amount} a month, will be ${
              include ? "added to" : "taken out of"
            } the candidate monthly income. The figures update at once. Your reason is kept in the audit record, next to what the method said.`
          : ""
      }
      note={
        component
          ? `The method says: ${component.rule_included ? "counted" : "left out"}${
              component.rule_note ? `. ${component.rule_note}` : "."
            }`
          : undefined
      }
      confirmLabel={include ? "Include in candidate" : "Exclude from candidate"}
      maxLength={INCOME_REASON_MAX}
      onConfirm={(reason) => onConfirm(include, reason)}
    />
  );
}
