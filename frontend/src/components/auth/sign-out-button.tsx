"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";

/** Forgets the sign-in on this browser, then shows the sign-in page. */
export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const signOut = async () => {
    setBusy(true);
    try {
      await fetch("/api/session/logout", { method: "POST" });
    } catch {
      // The cookies are cleared by the server; if it cannot be reached, the next call asks for sign-in.
    }
    router.replace("/login");
    router.refresh();
  };

  return (
    <Button variant="outline" size="sm" className="w-full justify-center" onClick={signOut} disabled={busy}>
      <LogOut className="size-3.5" />
      {busy ? "Signing out…" : "Sign out"}
    </Button>
  );
}
