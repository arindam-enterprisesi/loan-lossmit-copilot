import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { DocStatusChip } from "@/components/shared/doc-status-chip";
import { FlagChip, severityTone } from "@/components/shared/flag-chip";
import { StatCard } from "@/components/shared/stat-card";
import { flagGroupLabel, flagGroupTitle, groupFlags } from "@/lib/flags";
import { humanize } from "@/lib/format";
import { PILLARS, pillarFromSlug } from "@/lib/nav";
import { loadCases, loadDocuments } from "@/lib/server-api";
import { MOCK_CASE_REFS } from "@/mocks/data";

export default async function DashboardPage({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: slug } = await params;
  const pillar = pillarFromSlug(slug);
  if (!pillar) notFound();

  const cases = await loadCases(pillar);
  const docsByCase = await Promise.all(cases.map((c) => loadDocuments(c.id)));
  const docs = docsByCase.flat();
  const caseTitle = new Map(cases.map((c) => [c.id, c.title]));

  const needsReview = docs.filter((d) => d.status === "needs_review").length;
  const typeNeeded = docs.filter((d) => d.status === "type_needed").length;
  const attention = docs.filter((d) => d.status === "needs_review" || d.status === "type_needed");

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={`${PILLARS[pillar].title}. Synthetic data, for demonstration only.`}
      />

      <section aria-label="Summary" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard value={cases.length} label="Cases" />
        <StatCard value={docs.length} label="Documents" />
        <StatCard value={needsReview} label="Needs review" hint="Documents with flagged fields" />
        <StatCard value={typeNeeded} label="Type needed" hint="Waiting for a person to pick a type" />
      </section>

      <section aria-label="Needs attention" className="mt-8">
        <h2 className="text-lg">Needs attention</h2>
        {attention.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">Nothing is waiting for review.</p>
        ) : (
          <ul className="mt-3 divide-y rounded-xl border bg-card">
            {attention.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-navy">{d.file_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {caseTitle.get(d.case_id) ?? "Case"} ·{" "}
                    {d.doc_type ? humanize(d.doc_type) : "Type not set"}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {groupFlags(d.flags).map((g) => (
                    <FlagChip key={g.code} tone={severityTone(g.severity)} title={flagGroupTitle(g)}>
                      {flagGroupLabel(g)}
                    </FlagChip>
                  ))}
                  <DocStatusChip status={d.status} />
                </div>
                {d.flags[0] ? (
                  <p className="w-full text-xs text-muted-foreground">{d.flags[0].message}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Cases" className="mt-8">
        <h2 className="text-lg">Cases</h2>
        <ul className="mt-3 grid gap-3 md:grid-cols-2">
          {cases.map((c) => (
            <li key={c.id} className="rounded-xl border bg-card p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-gold">
                {c.case_ref ?? MOCK_CASE_REFS[c.id] ?? c.id.slice(0, 8)}
              </div>
              <div className="mt-1 font-heading text-base font-bold text-navy">{c.title}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {c.document_count ?? 0} documents
              </div>
            </li>
          ))}
        </ul>
      </section>

      <p className="mt-10 text-xs text-muted-foreground">
        The copilot reads documents and shows its working. People make every decision.
      </p>
    </>
  );
}
