import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorNoticeProps {
  message: string;
  /** When given, shows a button that runs the failed step again. */
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

/**
 * A failure that stops a screen from showing what it should (it could not load, or a run failed).
 * It sits where the content would be, says what went wrong, and gives another try. For a failure
 * of one action while the screen is fine, use a toast instead.
 */
export function ErrorNotice({ message, onRetry, retryLabel = "Try again", className }: ErrorNoticeProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-navy",
        className,
      )}
    >
      <span>{message}</span>
      {onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}
