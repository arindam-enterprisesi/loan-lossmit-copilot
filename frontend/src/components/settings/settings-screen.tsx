import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { mocksOn } from "@/lib/backend-url";
import { findNavItem, pillarFromSlug } from "@/lib/nav";
import { parseSessionUser, USER_COOKIE } from "@/lib/session";
import { canSeeSettings } from "@/lib/settings";
import { SettingsWorkspace } from "./settings-workspace";

/** Server shell for the settings menu item, in both pillars. Only an administrator may open it. */
export async function SettingsScreen({ params }: { params: Promise<{ pillar: string }> }) {
  const { pillar: pillarSlug } = await params;
  const pillar = pillarFromSlug(pillarSlug);
  const item = pillar ? findNavItem(pillar, "context-settings") : undefined;
  if (!pillar || !item) notFound();

  // With the demo data nobody signs in. Otherwise the role decides; the backend refuses anyone else as well.
  const role = mocksOn() ? null : (parseSessionUser((await cookies()).get(USER_COOKIE)?.value)?.role ?? "none");

  return (
    <>
      <PageHeader title={item.label} description="Which model does each task, and the version and label of every setting. For administrators, read-only." />
      {canSeeSettings(role) ? (
        <SettingsWorkspace />
      ) : (
        <EmptyState title="Settings are for administrators">Sign in as an administrator to see which models and settings are in force.</EmptyState>
      )}
    </>
  );
}
