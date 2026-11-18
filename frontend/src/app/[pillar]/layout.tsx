import { notFound } from "next/navigation";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { pillarFromSlug } from "@/lib/nav";

export default async function PillarLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ pillar: string }>;
}) {
  const { pillar: slug } = await params;
  const pillar = pillarFromSlug(slug);
  if (!pillar) notFound();

  return (
    <div className="flex min-h-screen">
      <AppSidebar pillar={pillar} />
      <main className="min-w-0 flex-1 bg-background px-8 py-7">{children}</main>
    </div>
  );
}
