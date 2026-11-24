import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { HardshipWorkspace } from "./hardship-workspace";
import { NoCases } from "@/components/shared/no-cases";

/** Server shell for the "Hardship and budget" menu item. Only the Loss Mitigation pillar has it. */
export async function HardshipScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "hardship-budget") : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="The hardship letter, read and checked against the documents, and the monthly budget as stated and as observed. A person confirms every judgement."
      />
      {cases.length === 0 ? <NoCases /> : <HardshipWorkspace cases={cases} pillarSlug={pillarSlug} />}
    </>
  );
}
