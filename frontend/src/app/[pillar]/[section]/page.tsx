import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { findNavItem, pillarFromSlug } from "@/lib/nav";

// Placeholder for menu items whose screen is not built yet. A real screen replaces this by adding
// a static folder next to it (e.g. app/[pillar]/income-analysis/page.tsx), which takes precedence.
export default async function SectionPlaceholder({
  params,
}: {
  params: Promise<{ pillar: string; section: string }>;
}) {
  const { pillar: pillarSlug, section } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, section) : undefined;
  if (!pillar || !item) notFound();

  return (
    <>
      <PageHeader title={item.label} description="This screen is not part of this demo yet." />
      <EmptyState title={`${item.label} is not available yet`}>
        It is on the menu so the whole product can be seen, but it has nothing to show in this demo. Pick another item from the menu.
      </EmptyState>
    </>
  );
}
