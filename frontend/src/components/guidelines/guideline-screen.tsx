import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { GuidelineWorkspace } from "./guideline-workspace";

/** Server shell for the "Guideline assistant" menu item, in both pillars. */
export async function GuidelineScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "guideline-assistant") : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="Ask a question and read a short answer that cites the loaded guides and regulation. The sources decide what is said; a person decides what to do."
      />
      <GuidelineWorkspace cases={cases} defaultSourceSet={pillar === "loss_mitigation" ? "regulation_x" : "all"} />
    </>
  );
}
