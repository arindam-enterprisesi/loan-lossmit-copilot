import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { loadCases } from "@/lib/server-api";
import { HitlWorkspace } from "./hitl-workspace";
import { NoCases } from "@/components/shared/no-cases";

/** Server shell for the "HITL actions" menu item, in both pillars. */
export async function HitlScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "hitl-actions") : undefined;
  if (!pillar || !item) notFound();

  const cases = await loadCases(pillar);
  return (
    <>
      <PageHeader
        title={item.label}
        description="Every review action on a case: who confirmed, corrected, overrode, decided or signed off, when, and why. The record only grows."
      />
      {cases.length === 0 ? <NoCases /> : <HitlWorkspace cases={cases} />}
    </>
  );
}
