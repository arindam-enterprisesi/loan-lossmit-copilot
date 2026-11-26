import { cn } from "@/lib/utils";
import type { Severity } from "@/lib/types";

export type ChipTone = "danger" | "warning" | "success" | "neutral" | "info";

const toneClasses: Record<ChipTone, string> = {
  danger: "bg-danger/12 text-danger ring-danger/25",
  warning: "bg-gold/15 text-[#7a5f2e] ring-gold/35",
  success: "bg-success/12 text-success ring-success/25",
  info: "bg-teal/10 text-teal ring-teal/25",
  neutral: "bg-neutral-chip/12 text-neutral-chip ring-neutral-chip/25",
};

/** Maps a contract Severity to a chip tone. */
export function severityTone(severity: Severity): ChipTone {
  return severity === "error" ? "danger" : severity === "warning" ? "warning" : "info";
}

interface FlagChipProps {
  tone: ChipTone;
  children: React.ReactNode;
  className?: string;
  /** Shown on hover, for what the chip stands for when its text is only a code. */
  title?: string;
}

/** Small pill for flags and statuses: High / Medium / Low, Consistent, Excluded, Source needed. */
export function FlagChip({ tone, children, className, title }: FlagChipProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset whitespace-nowrap",
        toneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
