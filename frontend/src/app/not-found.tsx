import Link from "next/link";

/** An address that is not a screen of this app. It says so and leads back, in the same plain style as the error page. */
export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-4 py-24 text-center">
      <h1 className="mb-3 text-xl">This page does not exist</h1>
      <p className="mb-6 text-sm text-muted-foreground">The address may be wrong, or the screen may have moved. Go back to a copilot to carry on.</p>
      <div className="flex justify-center gap-4 text-sm">
        <Link href="/underwriting" className="underline underline-offset-2">
          Loan Processing
        </Link>
        <Link href="/loss-mitigation" className="underline underline-offset-2">
          Loss Mitigation
        </Link>
      </div>
    </div>
  );
}
