"use client";

import { useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { ShowWorkingDrawer } from "@/components/shared/show-working-drawer";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ASSET_REASON_MAX, figureText, SOURCE_LABEL } from "@/lib/assets";
import type { AssetFigure, AssetObligation } from "@/lib/assets-types";
import { formatDate, formatMoney } from "@/lib/format";
import { workingEvidence } from "@/lib/income";

interface ObligationsTableProps {
  obligations: AssetObligation[];
  /** The total of the debts that count, with its working. */
  total: AssetFigure | null;
  caseId: string;
  pillarSlug: string;
  /** Counts a debt toward the DTI or leaves it out. If it throws, the window stays open and shows why. Without it there are no buttons. */
  onDecide?: (obligationId: string, counts: boolean, reason: string) => Promise<void>;
}

/**
 * Each recurring debt, where it was found (bank, credit report or both), and whether it counts toward
 * the DTI. A person decides which count, with a reason; the ratios update at once. What the settings
 * decided stays visible beside the change.
 */
export function ObligationsTable({ obligations, total, caseId, pillarSlug, onDecide }: ObligationsTableProps) {
  const [deciding, setDeciding] = useState<AssetObligation | null>(null);

  if (obligations.length === 0) {
    return <p className="rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground">No recurring debts were found.</p>;
  }

  const include = deciding ? !deciding.counts_toward_dti : false;
  return (
    <div className="rounded-xl border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Debt</TableHead>
            <TableHead className="text-right">Monthly payment</TableHead>
            <TableHead className="text-right">Balance</TableHead>
            <TableHead>Found in</TableHead>
            <TableHead>Counts toward DTI</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {obligations.map((o) => (
            <TableRow key={o.id} data-testid={`obligation-${o.id}`}>
              <TableCell className="align-top whitespace-normal">
                <div className="font-semibold text-navy">{o.creditor}</div>
                <div className="text-xs text-muted-foreground">{o.kind}</div>
              </TableCell>
              <TableCell className="text-right align-top font-mono">{formatMoney(o.monthly_payment)}</TableCell>
              <TableCell className="text-right align-top font-mono">{formatMoney(o.balance)}</TableCell>
              <TableCell className="align-top">
                <FlagChip tone={o.source === "both" ? "success" : "neutral"}>{SOURCE_LABEL[o.source]}</FlagChip>
              </TableCell>
              <TableCell className="align-top whitespace-normal">
                <div className="flex flex-wrap items-center gap-2">
                  <FlagChip tone={o.counts_toward_dti ? "success" : "neutral"}>{o.counts_toward_dti ? "Counted" : "Left out"}</FlagChip>
                  {onDecide ? (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={`${o.counts_toward_dti ? "Exclude" : "Include"} ${o.creditor}`}
                      onClick={() => setDeciding(o)}
                    >
                      {o.counts_toward_dti ? "Exclude" : "Include"}
                    </Button>
                  ) : null}
                </div>
                {o.change ? (
                  <div className="mt-1 max-w-60 space-y-0.5 text-xs text-muted-foreground">
                    <div>
                      {o.counts_toward_dti ? "Included" : "Excluded"} by {o.change.by}, {formatDate(o.change.at)}
                    </div>
                    <div>Reason: {o.change.reason}</div>
                    <div>
                      The settings said: {o.system_counts_toward_dti ? "counted" : "left out"}. {o.reason}
                    </div>
                  </div>
                ) : (
                  <div className="mt-1 max-w-60 text-xs text-muted-foreground">{o.reason}</div>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        <TableFooter>
          <TableRow data-testid="obligations-total">
            <TableCell colSpan={4}>
              <div className="font-semibold text-navy">Monthly obligations counted</div>
              <div className="text-xs font-normal text-muted-foreground">The underwriter decides which debts count.</div>
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-3">
                <span className="font-mono text-base font-semibold text-navy">{figureText(total)}</span>
                {total ? (
                  <ShowWorkingDrawer
                    title="Monthly obligations counted"
                    steps={total.working}
                    evidence={workingEvidence(total.evidence, pillarSlug, caseId)}
                    triggerAriaLabel="Show working for Monthly obligations counted"
                  />
                ) : null}
              </div>
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>

      {onDecide ? (
        <ReasonDialog
          open={deciding !== null}
          onOpenChange={(open) => {
            if (!open) setDeciding(null);
          }}
          title={deciding ? `${include ? "Include" : "Exclude"} ${deciding.creditor}` : ""}
          description={
            deciding
              ? `${deciding.creditor}, ${formatMoney(deciding.monthly_payment)} a month, will be ${
                  include ? "counted in" : "left out of"
                } the DTI. The ratios update at once. Your reason is kept in the audit record, next to what the settings said.`
              : ""
          }
          note={deciding ? `The settings say: ${deciding.system_counts_toward_dti ? "counted" : "left out"}. ${deciding.reason}` : undefined}
          confirmLabel={include ? "Include in DTI" : "Exclude from DTI"}
          maxLength={ASSET_REASON_MAX}
          onConfirm={(reason) => onDecide(deciding!.id, include, reason)}
        />
      ) : null}
    </div>
  );
}
