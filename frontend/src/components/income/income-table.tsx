"use client";

import { useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { ShowWorkingDrawer } from "@/components/shared/show-working-drawer";
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
import { CANDIDATE_LABEL, workingEvidence } from "@/lib/income";
import type { IncomeAnalysis, IncomeComponent, IncomeFigure } from "@/lib/income-types";
import { IncomeDecisionDialog } from "./income-decision-dialog";

interface IncomeTableProps {
  analysis: IncomeAnalysis;
  pillarSlug: string;
  /**
   * Sends a person's include or exclude decision. Without it the table is read-only (no buttons).
   * If it throws, the dialog stays open and shows the message.
   */
  onDecide?: (componentId: string, included: boolean, reason: string) => Promise<void>;
}

/** One figure with its own Show working drawer. A missing figure is a dash; a plain amount with no working has no button. */
function FigureCell({
  figure,
  title,
  analysis,
  pillarSlug,
  strong,
}: {
  figure: IncomeFigure | null;
  title: string;
  analysis: IncomeAnalysis;
  pillarSlug: string;
  strong?: boolean;
}) {
  if (!figure) return <TableCell className="text-right text-muted-foreground">—</TableCell>;
  return (
    <TableCell className="text-right">
      <div className="flex items-center justify-end gap-2">
        <span className={strong ? "font-semibold text-navy" : undefined}>{formatMoney(figure.value)}</span>
        {figure.working.length > 0 ? (
          <ShowWorkingDrawer
            title={title}
            steps={figure.working}
            evidence={workingEvidence(figure.evidence, pillarSlug, analysis.case_id)}
            triggerLabel="Working"
            triggerAriaLabel={`Show working for ${title}`}
          />
        ) : null}
      </div>
    </TableCell>
  );
}

/** Income components: current period, year to date and monthly, plus the candidate total. */
export function IncomeTable({ analysis, pillarSlug, onDecide }: IncomeTableProps) {
  const [deciding, setDeciding] = useState<IncomeComponent | null>(null);
  return (
    <div className="rounded-xl border bg-card">
      <Table>
        <TableCaption className="sr-only">
          Income components with current period, year to date and monthly amounts in US dollars
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Component</TableHead>
            <TableHead className="text-right">Current period</TableHead>
            <TableHead className="text-right">Year to date</TableHead>
            <TableHead className="text-right">Monthly</TableHead>
            <TableHead>Counted</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {analysis.components.map((c) => (
            <TableRow key={c.id} data-testid={`component-${c.id}`}>
              <TableCell className="font-semibold text-navy">{c.label}</TableCell>
              <FigureCell
                figure={c.current_period}
                title={`${c.label}, current period`}
                analysis={analysis}
                pillarSlug={pillarSlug}
              />
              <FigureCell
                figure={c.year_to_date}
                title={`${c.label}, year to date`}
                analysis={analysis}
                pillarSlug={pillarSlug}
              />
              <FigureCell
                figure={c.monthly}
                title={`${c.label}, monthly`}
                analysis={analysis}
                pillarSlug={pillarSlug}
                strong
              />
              <TableCell>
                <div className="flex flex-wrap items-center gap-2">
                  <FlagChip tone={c.included ? "success" : "neutral"}>{c.included ? "Counted" : "Left out"}</FlagChip>
                  {onDecide ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDeciding(c)}
                      aria-label={`${c.included ? "Exclude" : "Include"} ${c.label}`}
                    >
                      {c.included ? "Exclude" : "Include"}
                    </Button>
                  ) : null}
                </div>
                {c.override ? (
                  <div className="mt-1 max-w-56 space-y-0.5 whitespace-normal text-xs text-muted-foreground">
                    <div>
                      {c.override.included ? "Included" : "Excluded"} by {c.override.by}, {formatDate(c.override.at)}
                    </div>
                    <div>Reason: {c.override.reason}</div>
                    <div>
                      The method said: {c.rule_included ? "counted" : "left out"}
                      {c.rule_note ? `. ${c.rule_note}` : ""}
                    </div>
                  </div>
                ) : !c.included && c.rule_note ? (
                  <div className="mt-1 max-w-56 whitespace-normal text-xs text-muted-foreground">{c.rule_note}</div>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        <TableFooter>
          <TableRow data-testid="candidate-row">
            <TableCell colSpan={3}>
              <div className="font-semibold text-navy">Candidate monthly income</div>
              <div className="text-xs font-normal text-muted-foreground">{analysis.candidate_label ?? CANDIDATE_LABEL}</div>
            </TableCell>
            <FigureCell
              figure={analysis.candidate_monthly}
              title="Candidate monthly income"
              analysis={analysis}
              pillarSlug={pillarSlug}
              strong
            />
            <TableCell />
          </TableRow>
        </TableFooter>
      </Table>
      {onDecide ? (
        <IncomeDecisionDialog
          component={deciding}
          onOpenChange={(open) => {
            if (!open) setDeciding(null);
          }}
          onConfirm={(included, reason) => onDecide(deciding!.id, included, reason)}
        />
      ) : null}
    </div>
  );
}
