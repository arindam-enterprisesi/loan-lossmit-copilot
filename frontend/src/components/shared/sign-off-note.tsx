import { cn } from "@/lib/utils";

/**
 * Standing reminder next to every sign-off control. Sign-off records that a person reviewed the
 * work; it is never a decision (CLAUDE.md rule 3).
 */
export function SignOffNote({ className }: { className?: string }) {
  return (
    <p className={cn("text-xs text-muted-foreground", className)}>
      Records a review. Not a decision.
    </p>
  );
}
