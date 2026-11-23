"use client";

import { useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate, formatMoney } from "@/lib/format";
import { AMOUNT_PATTERN, HARDSHIP_REASON_MAX, signedMoney } from "@/lib/hardship";
import type { Budget, BudgetLine } from "@/lib/hardship-types";
import { cn } from "@/lib/utils";

interface BudgetTableProps {
  budget: Budget;
  /**
   * Sends an adjustment. Without it the table is read-only (no buttons). If it throws, the window
   * stays open and shows the message.
   */
  onAdjust?: (itemId: string, amount: string, reason: string) => Promise<void>;
}

/** Stated figures beside observed ones by category, with differences highlighted. */
export function BudgetTable({ budget, onAdjust }: BudgetTableProps) {
  const [adjusting, setAdjusting] = useState<BudgetLine | null>(null);

  return (
    <div className="space-y-2">
      <div className="rounded-xl border bg-card">
        <Table>
          <TableCaption className="sr-only">
            Monthly expenses by category: stated on the application against observed in the documents, in US dollars
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Category</TableHead>
              <TableHead className="text-right">Stated</TableHead>
              <TableHead className="text-right">Observed</TableHead>
              <TableHead className="text-right">Difference</TableHead>
              {onAdjust ? <TableHead /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {budget.lines.map((l) => (
              <TableRow key={l.id} data-testid={`budget-${l.id}`} className={cn(l.flagged && "bg-gold/10")}>
                <TableCell className="max-w-72 whitespace-normal align-top">
                  <div className="font-semibold text-navy">{l.category}</div>
                  {l.flag_message ? <div className="mt-0.5 text-xs font-normal text-navy">{l.flag_message}</div> : null}
                  {l.adjustment ? (
                    <div className="mt-1 space-y-0.5 text-xs font-normal text-muted-foreground">
                      <div>
                        Adjusted by {l.adjustment.by}, {formatDate(l.adjustment.at)}. Documents showed{" "}
                        {formatMoney(l.adjustment.original_observed)}.
                      </div>
                      <div>Reason: {l.adjustment.reason}</div>
                    </div>
                  ) : null}
                </TableCell>
                <TableCell className="text-right align-top">{formatMoney(l.stated)}</TableCell>
                <TableCell className="text-right align-top font-semibold text-navy">{formatMoney(l.observed)}</TableCell>
                <TableCell className="text-right align-top">
                  <div className={cn(l.flagged && "font-semibold text-navy")}>{l.difference_unsigned ? formatMoney(l.difference) : signedMoney(l.difference)}</div>
                  {l.flagged ? <FlagChip tone="warning">Flagged</FlagChip> : null}
                </TableCell>
                {onAdjust ? (
                  <TableCell className="align-top">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setAdjusting(l)}
                      aria-label={`Adjust ${l.category}`}
                    >
                      Adjust
                    </Button>
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow data-testid="budget-total">
              <TableCell className="font-semibold text-navy">Total expenses</TableCell>
              <TableCell className="text-right">{formatMoney(budget.stated_total)}</TableCell>
              <TableCell className="text-right font-semibold text-navy">{formatMoney(budget.observed_total)}</TableCell>
              <TableCell />
              {onAdjust ? <TableCell /> : null}
            </TableRow>
          </TableFooter>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Observed basis: {budget.observed_basis}.</p>

      {onAdjust ? (
        <ReasonDialog
          open={adjusting !== null}
          onOpenChange={(open) => {
            if (!open) setAdjusting(null);
          }}
          title={adjusting ? `Adjust ${adjusting.category}` : ""}
          description="Set how much of this counts each month, for example to mark a spend as one-off. The measures update at once. Your reason is kept next to what the documents showed."
          note={
            adjusting
              ? `Stated ${formatMoney(adjusting.stated)}. The documents showed ${formatMoney(
                  adjusting.adjustment?.original_observed ?? adjusting.observed,
                )}.`
              : undefined
          }
          confirmLabel="Adjust item"
          maxLength={HARDSHIP_REASON_MAX}
          field={
            adjusting
              ? {
                  label: "Amount counted each month",
                  initialValue: adjusting.observed,
                  validate: (v) => (AMOUNT_PATTERN.test(v) ? null : "Enter an amount such as 200.00"),
                }
              : undefined
          }
          onConfirm={(reason, amount) => onAdjust(adjusting!.id, amount, reason)}
        />
      ) : null}
    </div>
  );
}
