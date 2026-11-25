import { cn } from "@/lib/utils";

interface EmptyStateProps {
  /** One short line in bold, e.g. "No documents yet". */
  title?: string;
  /** What to do next, in plain words. */
  children: React.ReactNode;
  /** A button or link that does it. */
  action?: React.ReactNode;
  className?: string;
}

/** "Nothing here yet", with what to do about it. Used instead of a blank area. */
export function EmptyState({ title, children, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-dashed bg-panel p-8 text-center text-sm text-muted-foreground",
        className,
      )}
    >
      {title ? <p className="mb-1 text-base font-semibold text-navy">{title}</p> : null}
      <p>{children}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
