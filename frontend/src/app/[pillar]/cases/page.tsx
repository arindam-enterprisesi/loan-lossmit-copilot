import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { NoCases } from "@/components/shared/no-cases";
import { FlagChip } from "@/components/shared/flag-chip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate, humanize } from "@/lib/format";
import { pillarFromSlug } from "@/lib/nav";
import { loadCases, loadDocuments } from "@/lib/server-api";
import { MOCK_CASE_REFS } from "@/mocks/data";

export default async function CasesPage({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: slug } = await params;
  const pillar = pillarFromSlug(slug);
  if (!pillar) notFound();

  const cases = await loadCases(pillar);
  if (cases.length === 0) {
    return (
      <>
        <PageHeader title="Cases" description="Each case groups the documents and results for one borrower." />
        <NoCases />
      </>
    );
  }
  const docs = await Promise.all(cases.map((c) => loadDocuments(c.id)));

  return (
    <>
      <PageHeader title="Cases" description="Each case groups the documents and results for one borrower." />
      <div className="rounded-xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Case</TableHead>
              <TableHead>Borrower</TableHead>
              <TableHead>Employment</TableHead>
              <TableHead className="text-right">Documents</TableHead>
              <TableHead>Needs review</TableHead>
              <TableHead>Reference date</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {cases.map((c, i) => {
              const review = docs[i].filter((d) => d.status === "needs_review").length;
              return (
                <TableRow key={c.id}>
                  <TableCell>
                    <div className="text-xs font-semibold uppercase tracking-wide text-gold">
                      {c.case_ref ?? MOCK_CASE_REFS[c.id] ?? c.id.slice(0, 8)}
                    </div>
                    <div className="font-semibold text-navy">{c.title}</div>
                  </TableCell>
                  <TableCell>{c.profile?.borrower_names.join(", ") ?? "—"}</TableCell>
                  <TableCell>{c.profile ? humanize(c.profile.employment_type) : "—"}</TableCell>
                  <TableCell className="text-right">{c.document_count ?? docs[i].length}</TableCell>
                  <TableCell>
                    {review > 0 ? (
                      <FlagChip tone="danger">{review} to review</FlagChip>
                    ) : (
                      <FlagChip tone="success">Clear</FlagChip>
                    )}
                  </TableCell>
                  <TableCell>{formatDate(c.profile?.reference_date)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
