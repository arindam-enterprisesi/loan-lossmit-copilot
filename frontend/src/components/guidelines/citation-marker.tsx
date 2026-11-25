import { cn } from "@/lib/utils";

interface CitationMarkerProps {
  marker: number;
  /** The section the marker opens, for its accessible name. */
  heading?: string;
  onOpen: (marker: number) => void;
  className?: string;
}

/** A numbered marker at the end of a sentence. It opens the passage that supports the sentence. */
export function CitationMarker({ marker, heading, onOpen, className }: CitationMarkerProps) {
  return (
    <button
      type="button"
      onClick={() => onOpen(marker)}
      aria-label={`Open citation ${marker}${heading ? `: ${heading}` : ""}`}
      className={cn(
        "mx-0.5 inline-flex min-w-5 items-center justify-center rounded-md bg-teal/10 px-1 align-baseline text-[11px] font-bold text-teal ring-1 ring-teal/25 transition-colors hover:bg-teal hover:text-white focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {marker}
    </button>
  );
}
