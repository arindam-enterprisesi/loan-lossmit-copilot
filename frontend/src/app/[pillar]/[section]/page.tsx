import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
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
      <PageHeader title={item.label} description="This screen is coming in a later build day." />
      <div className="rounded-xl border border-dashed bg-panel p-10 text-center text-sm text-muted-foreground">
        {item.label} is not built yet.
      </div>
    </>
  );
}
