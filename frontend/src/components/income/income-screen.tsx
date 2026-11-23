import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { IncomeWorkspace } from "./income-workspace";

/** Server shell for the "Income analysis" menu item. Only the Loan Processing pillar has it. */
export async function IncomeScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "income-analysis") : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="Income by component with the working behind each figure. A person decides what counts."
      />
      <IncomeWorkspace cases={cases} pillarSlug={pillarSlug} />
    </>
  );
}
