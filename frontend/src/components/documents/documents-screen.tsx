import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { DocumentsWorkspace } from "./documents-workspace";
import { ReviewWorkspace } from "./review-workspace";

type Params = Promise<{ pillar: string }>;

/**
 * Server shells shared by the two menu items that show documents: "Document intelligence"
 * (Loan Processing) and "Document intake" (Loss Mitigation). `section` is the menu item's URL slug.
 */
export async function DocumentsScreen({ params, section }: { params: Params; section: string }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, section) : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="Upload documents, then review what was read from each one next to the page."
      />
      <DocumentsWorkspace cases={cases} pillarSlug={pillarSlug} section={section} />
    </>
  );
}

export async function ReviewScreen({
  params,
  section,
}: {
  params: Promise<{ pillar: string; caseId: string; documentId: string }>;
  section: string;
}) {
  const { pillar: pillarSlug, caseId, documentId } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  if (!pillar || !findNavItem(pillar, section)) notFound();

  return (
    <ReviewWorkspace caseId={caseId} documentId={documentId} backHref={`/${pillarSlug}/${section}`} />
  );
}
