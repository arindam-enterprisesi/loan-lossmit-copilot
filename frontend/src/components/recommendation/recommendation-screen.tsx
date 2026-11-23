import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { RecommendationWorkspace } from "./recommendation-workspace";

/** Server shell for the "Recommendation" menu item. Only the Loss Mitigation pillar has it. */
export async function RecommendationScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "recommendation") : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="The lender's view first, then each option's conditions in the investor's order. A draft for a person to review. It decides nothing."
      />
      <RecommendationWorkspace cases={cases} />
    </>
  );
}
