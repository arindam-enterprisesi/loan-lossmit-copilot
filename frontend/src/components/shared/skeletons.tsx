import { Skeleton } from "@/components/ui/skeleton";

/** Loading stand-in for a table: a header row and a few body rows, so the page does not jump. */
export function TableSkeleton({
  rows = 4,
  columns = 4,
  label = "Loading",
}: {
  rows?: number;
  columns?: number;
  label?: string;
}) {
  const cols = { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` };
  return (
    <div role="status" aria-label={label} className="space-y-2 rounded-xl border bg-card p-4">
      <span className="sr-only">{label}…</span>
      <div className="grid gap-4" style={cols}>
        {Array.from({ length: columns }, (_, c) => (
          <Skeleton key={c} className="h-4 w-2/3" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="grid gap-4 border-t pt-2" style={cols}>
          {Array.from({ length: columns }, (_, c) => (
            <Skeleton key={c} className="h-7 w-full" />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Loading stand-in for a stack of cards (flags, profile items). */
export function CardsSkeleton({ count = 3, label = "Loading" }: { count?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="space-y-2 rounded-xl border bg-card p-4">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-full" />
        </div>
      ))}
    </div>
  );
}

/** Loading stand-in for a page beside a list of fields (the review screen). */
export function SplitSkeleton({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-label={label} className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <span className="sr-only">{label}…</span>
      <Skeleton className="h-[28rem] w-full" />
      <div className="space-y-3">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="space-y-2 rounded-lg border bg-card p-3">
            <Skeleton className="h-3 w-1/4" />
            <Skeleton className="h-5 w-1/2" />
          </div>
        ))}
      </div>
    </div>
  );
}
