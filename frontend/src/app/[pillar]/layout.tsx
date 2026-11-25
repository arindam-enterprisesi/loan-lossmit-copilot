import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { ToastProvider } from "@/components/shared/toast";
import { mocksOn } from "@/lib/backend-url";
import { pillarFromSlug } from "@/lib/nav";
import { canSeePillar, homePathFor, parseSessionUser, USER_COOKIE, type SessionUser } from "@/lib/session";

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

  // With the demo data on nobody signs in. Otherwise the person must be known, and may only be in a
  // pillar their role can see (the backend hides the other one's cases from them anyway).
  let user: SessionUser | null = null;
  if (!mocksOn()) {
    user = parseSessionUser((await cookies()).get(USER_COOKIE)?.value);
    if (!user) redirect("/login");
    if (!canSeePillar(user, pillar)) redirect(homePathFor(user.role));
  }

  return (
    <div className="flex min-h-screen">
      <AppSidebar pillar={pillar} user={user} />
      <ToastProvider>
        <main className="min-w-0 flex-1 bg-background px-8 py-7">{children}</main>
      </ToastProvider>
    </div>
  );
}
