"use client";

import Link from "next/link";
import { useState } from "react";
import { FlagChip, severityTone } from "@/components/shared/flag-chip";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  accountLabel,
  ASSET_REASON_MAX,
  canMarkSourced,
  categoryLabel,
  FLAG_SHORT_LABEL,
  groupByAccount,
  needsAttention,
  TRANSACTION_CATEGORIES,
} from "@/lib/assets";
import type { AssetTransaction, TransactionCategory } from "@/lib/assets-types";
import { formatDate, formatMoney } from "@/lib/format";
import { documentHref } from "@/lib/income";
import { cn } from "@/lib/utils";

interface TransactionsTableProps {
  transactions: AssetTransaction[];
  caseId: string;
  pillarSlug: string;
  /** Gives a line another category. If it throws, the window stays open and shows why. Without it there is no Reclassify button. */
  onReclassify?: (transactionId: string, category: TransactionCategory, reason: string) => Promise<void>;
  /** Marks a deposit as sourced (or removes the mark). Same rule on failure. */
  onSource?: (transactionId: string, sourced: boolean, reason: string) => Promise<void>;
}

type Editing = { kind: "category"; t: AssetTransaction } | { kind: "sourced"; t: AssetTransaction; sourced: boolean } | null;

const id = (t: AssetTransaction) => `${t.description} (${t.line_id})`;

/**
 * Every bank line of each account, with its category chip and flags. A person can give a line another
 * category, or mark a deposit as sourced with a note. What the system chose stays visible beside the
 * change, with who changed it, when and why.
 */
export function TransactionsTable({ transactions, caseId, pillarSlug, onReclassify, onSource }: TransactionsTableProps) {
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [editing, setEditing] = useState<Editing>(null);
  const attention = transactions.filter(needsAttention).length;

  if (transactions.length === 0) {
    return <p className="rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground">No bank lines were found.</p>;
  }

  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 text-sm text-navy">
        <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />
        Only lines that need a look ({attention})
      </label>

      {groupByAccount(transactions).map((group) => {
        const rows = onlyFlagged ? group.transactions.filter(needsAttention) : group.transactions;
        return (
          <section key={group.account ?? "none"} aria-label={accountLabel(group.account)} className="rounded-xl border bg-card">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b px-4 py-2.5">
              <h3 className="text-base text-navy">{accountLabel(group.account)}</h3>
              <span className="text-xs text-muted-foreground">
                {rows.length === group.transactions.length ? `${rows.length} lines` : `${rows.length} of ${group.transactions.length} lines`}
              </span>
            </div>
            {rows.length === 0 ? (
              <p className="px-4 py-3 text-sm text-muted-foreground">No lines need a look on this account.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Flags</TableHead>
                    {onReclassify || onSource ? <TableHead className="text-right">Action</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((t) => (
                    <TableRow key={t.id} data-testid={`transaction-${t.id}`} className={cn(needsAttention(t) && "bg-gold/10")}>
                      <TableCell className="whitespace-nowrap align-top">{formatDate(t.posted_on)}</TableCell>
                      <TableCell className="align-top whitespace-normal">
                        <div className="font-semibold text-navy">{t.description}</div>
                        <div className="text-xs text-muted-foreground">
                          {t.counterparty ? `${t.counterparty} · ` : ""}
                          <Link href={documentHref(pillarSlug, caseId, t.document_id)} className="underline underline-offset-2">
                            line {t.line_id}
                          </Link>
                        </div>
                      </TableCell>
                      <TableCell className={cn("text-right align-top font-mono", t.direction === "credit" ? "text-teal" : "text-navy")}>
                        {formatMoney(t.amount)}
                      </TableCell>
                      <TableCell className="align-top whitespace-normal">
                        <FlagChip tone={t.category_source === "user" ? "info" : "neutral"}>{categoryLabel(t.category)}</FlagChip>
                        {t.change ? (
                          <div className="mt-1 max-w-56 space-y-0.5 whitespace-normal text-xs text-muted-foreground">
                            <div>
                              {t.category_source === "user" ? "Changed" : "Updated"} by {t.change.by}, {formatDate(t.change.at)}
                            </div>
                            <div>Reason: {t.change.reason}</div>
                            {t.category_source === "user" ? <div>The system said: {categoryLabel(t.system_category)}</div> : null}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="align-top whitespace-normal">
                        <div className="flex max-w-60 flex-wrap gap-1">
                          {t.payroll_match ? (
                            <span title={t.payroll_match}>
                              <FlagChip tone="success">Matches pay stub</FlagChip>
                            </span>
                          ) : null}
                          {t.needs_review ? <FlagChip tone="warning">Needs review</FlagChip> : null}
                          {t.flags.map((f) => (
                            <span key={f.code} title={f.message}>
                              <FlagChip tone={severityTone(f.severity)}>{FLAG_SHORT_LABEL[f.code] ?? f.code}</FlagChip>
                            </span>
                          ))}
                          {t.sourced ? <FlagChip tone="success">Sourced</FlagChip> : null}
                        </div>
                        {t.sourced && t.sourced_note ? (
                          <div className="mt-1 max-w-56 whitespace-normal text-xs text-muted-foreground">Source: {t.sourced_note}</div>
                        ) : null}
                        {t.flags.map((f) => (
                          <div key={`${f.code}-m`} className="mt-1 max-w-60 text-xs text-muted-foreground">
                            {f.message}
                          </div>
                        ))}
                      </TableCell>
                      {onReclassify || onSource ? (
                        <TableCell className="align-top">
                          <div className="flex flex-wrap justify-end gap-1.5">
                            {onReclassify ? (
                              <Button variant="outline" size="sm" aria-label={`Reclassify ${id(t)}`} onClick={() => setEditing({ kind: "category", t })}>
                                Reclassify
                              </Button>
                            ) : null}
                            {onSource && canMarkSourced(t) ? (
                              <Button
                                variant="outline"
                                size="sm"
                                aria-label={`${t.sourced ? "Remove the sourced mark from" : "Mark as sourced:"} ${id(t)}`}
                                onClick={() => setEditing({ kind: "sourced", t, sourced: !t.sourced })}
                              >
                                {t.sourced ? "Unmark sourced" : "Mark sourced"}
                              </Button>
                            ) : null}
                          </div>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>
        );
      })}

      {onReclassify ? (
        <ReasonDialog
          open={editing?.kind === "category"}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          title={editing?.kind === "category" ? `Reclassify ${editing.t.description}` : ""}
          description="Pick the category this line belongs in. Your reason is kept in the audit record, next to what the system chose."
          note={editing?.kind === "category" ? `The system labelled it: ${categoryLabel(editing.t.system_category)}` : undefined}
          confirmLabel="Save category"
          maxLength={ASSET_REASON_MAX}
          field={
            editing?.kind === "category"
              ? { label: "Category", initialValue: editing.t.category, options: TRANSACTION_CATEGORIES.map((c) => ({ value: c.value, label: c.label })) }
              : undefined
          }
          onConfirm={(reason, value) => onReclassify(editing!.t.id, value as TransactionCategory, reason)}
        />
      ) : null}

      {onSource ? (
        <ReasonDialog
          open={editing?.kind === "sourced"}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          title={editing?.kind === "sourced" ? (editing.sourced ? "Mark the deposit as sourced" : "Remove the sourced mark") : ""}
          description={
            editing?.kind === "sourced" && editing.sourced
              ? "Say where this deposit came from. The note is kept in the audit record, and the large-deposit flag shows as resolved."
              : "The large-deposit flag opens again. Say why the mark is being removed."
          }
          confirmLabel={editing?.kind === "sourced" && !editing.sourced ? "Remove mark" : "Mark as sourced"}
          maxLength={ASSET_REASON_MAX}
          onConfirm={(reason) => onSource(editing!.t.id, editing?.kind === "sourced" ? editing.sourced : true, reason)}
        />
      ) : null}
    </div>
  );
}
