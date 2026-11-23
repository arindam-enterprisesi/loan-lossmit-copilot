import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { AssetsWorkspace } from "./assets-workspace";

/** Server shell for the "Assets and liabilities" menu item. Only the Loan Processing pillar has it. */
export async function AssetsScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "assets-liabilities") : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="Documented assets, recurring debts and the candidate ratios, with the working behind each figure. A person decides what counts."
      />
      <AssetsWorkspace cases={cases} pillarSlug={pillarSlug} />
    </>
  );
}
