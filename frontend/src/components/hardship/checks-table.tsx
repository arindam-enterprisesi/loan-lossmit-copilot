import { FlagChip } from "@/components/shared/flag-chip";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ConsistencyCheck } from "@/lib/hardship-types";
import { cn } from "@/lib/utils";
import { SourceLine } from "./source-line";

interface ChecksTableProps {
  checks: ConsistencyCheck[];
  caseId: string;
  pillarSlug: string;
}

/** Stated against documented: each row shows both values with where each came from. */
export function ChecksTable({ checks, caseId, pillarSlug }: ChecksTableProps) {
  return (
    <div className="rounded-xl border bg-card">
      <Table>
        <TableCaption className="sr-only">Consistency checks: what was stated against what the documents show</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Check</TableHead>
            <TableHead>Stated</TableHead>
            <TableHead>Documented</TableHead>
            <TableHead>Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {checks.map((c) => (
            <TableRow key={c.id} data-testid={`check-${c.id}`} className={cn(c.status === "flagged" && "bg-gold/10")}>
              <TableCell className="max-w-64 whitespace-normal align-top">
                <div className="font-semibold text-navy">{c.label}</div>
                <div className="mt-0.5 text-xs font-normal text-muted-foreground">{c.detail}</div>
              </TableCell>
              <TableCell className="whitespace-normal align-top">
                <div className="text-navy">{c.stated.value}</div>
                <SourceLine source={c.stated.source} caseId={caseId} pillarSlug={pillarSlug} />
              </TableCell>
              <TableCell className="whitespace-normal align-top">
                <div className="text-navy">{c.documented.value}</div>
                <SourceLine source={c.documented.source} caseId={caseId} pillarSlug={pillarSlug} />
              </TableCell>
              <TableCell className="align-top">
                <FlagChip tone={c.status === "consistent" ? "success" : "warning"}>
                  {c.status === "consistent" ? "Consistent" : "Flagged"}
                </FlagChip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
