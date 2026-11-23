import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { UnderwritingCopilotWorkspace } from "./underwriting-copilot-workspace";

/** Server shell for the "Underwriting copilot" menu item. Only the Loan Processing pillar has it. */
export async function UnderwritingCopilotScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "underwriting-copilot") : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="Three agents research, write and check a draft report from the results of the earlier screens. The draft is for the underwriter to review; it decides nothing."
      />
      <UnderwritingCopilotWorkspace cases={cases} pillarSlug={pillarSlug} />
    </>
  );
}
