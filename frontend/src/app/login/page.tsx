import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { LoginForm } from "@/components/auth/login-form";
import { mocksOn } from "@/lib/backend-url";
import { homePathFor, parseSessionUser, safeNextPath, TOKEN_COOKIE, USER_COOKIE } from "@/lib/session";

export const metadata = { title: "Sign in · Mortgage Copilot" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ expired?: string; next?: string }>;
}) {
  // With the demo data on there is nothing to sign in to.
  if (mocksOn()) redirect("/");

  const { expired, next } = await searchParams;
  const store = await cookies();
  const user = parseSessionUser(store.get(USER_COOKIE)?.value);
  // Already signed in: go on. Not when the session just ended, or the old cookie would bounce back here.
  if (user && store.get(TOKEN_COOKIE)?.value && !expired) redirect(safeNextPath(next) ?? homePathFor(user.role));

  return (
    <main className="grid min-h-screen place-items-center bg-background px-4 py-10">
      <div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-sm">
        <h1 className="font-heading text-xl font-bold text-teal">Mortgage Copilot</h1>
        <p className="mt-1 mb-6 text-[11px] uppercase tracking-wider text-muted-foreground">Synthetic data only</p>
        <LoginForm expired={Boolean(expired)} next={next ?? null} />
        <p className="mt-6 text-xs text-muted-foreground">
          The copilot reads documents and shows its working. People make every decision.
        </p>
      </div>
    </main>
  );
}
