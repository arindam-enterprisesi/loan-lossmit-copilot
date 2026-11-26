"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorNotice } from "@/components/shared/error-notice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DEMO_USERNAMES, homePathFor, safeNextPath, type SessionUser } from "@/lib/session";

interface LoginFormProps {
  /** True when the person was sent here because their session ended. */
  expired?: boolean;
  /** Where they were going. Only an address inside this app is used. */
  next?: string | null;
}

/** Username and password. Sign-in goes through this app, which keeps the token out of the browser's scripts. */
export function LoginForm({ expired = false, next = null }: LoginFormProps) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/session/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = (await res.json().catch(() => ({}))) as { message?: string; user?: SessionUser };
      if (!res.ok || !data.user) {
        setError(data.message ?? `Sign-in did not work (the server answered ${res.status}).`);
        return;
      }
      router.replace(safeNextPath(next) ?? homePathFor(data.user.role));
      router.refresh();
    } catch {
      setError("The server could not be reached. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5" aria-label="Sign in">
      {expired ? (
        <p role="status" className="rounded-xl border border-gold/50 bg-gold/10 px-4 py-3 text-sm text-navy">
          Your session ended. Sign in again to continue.
        </p>
      ) : null}
      {error ? <ErrorNotice message={error} /> : null}

      <div className="space-y-1.5">
        <label htmlFor="username" className="text-xs font-semibold text-muted-foreground">
          Username
        </label>
        <Input
          id="username"
          name="username"
          autoComplete="username"
          autoFocus
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs text-muted-foreground">
          <span>Demo users:</span>
          {DEMO_USERNAMES.map((u) => (
            <button
              key={u.username}
              type="button"
              suppressHydrationWarning
              aria-label={`Use the ${u.label} username`}
              onClick={() => setUsername(u.username)}
              className="rounded-md border px-2 py-0.5 font-mono text-[11px] text-navy hover:bg-accent"
            >
              {u.username}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="password" className="text-xs font-semibold text-muted-foreground">
          Password
        </label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          For the demo users it is the DEMO_PASSWORD set in the backend&apos;s .env file.
        </p>
      </div>

      <Button type="submit" className="w-full" disabled={busy || !username.trim() || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
