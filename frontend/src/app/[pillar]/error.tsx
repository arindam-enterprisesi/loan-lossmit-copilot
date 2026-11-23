"use client";

import { ErrorNotice } from "@/components/shared/error-notice";

const FALLBACK = "The server could not load this page. Check that the backend is running, then try again.";

/**
 * A page that could not load (for example the backend is not running) says so, and can try again.
 * A production build hides the real message of a server error and puts a generic one in its place, so
 * that one is swapped for a plain sentence.
 */
export default function PillarError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const message = !error.message || error.message.includes("Server Components render") ? FALLBACK : error.message;
  return (
    <div className="mx-auto max-w-xl py-16">
      <h1 className="mb-4 text-xl">This page could not load</h1>
      <ErrorNotice message={message} onRetry={reset} />
    </div>
  );
}
