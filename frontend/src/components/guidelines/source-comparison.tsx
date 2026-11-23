import { FlagChip } from "@/components/shared/flag-chip";
import { LABEL_TEXT, passageFor } from "@/lib/guidelines";
import type { GuidelineAnswer } from "@/lib/guidelines-types";
import { CitationMarker } from "./citation-marker";

interface SourceComparisonProps {
  answer: GuidelineAnswer;
  onOpen: (marker: number) => void;
}

/**
 * Where the sources differ, such as an agency guide and a lender overlay, they are shown side by side so
 * the difference can be read at a glance. Each column says which document it is, how it is labelled, and
 * opens its passage. Nothing here says which source wins: that is for a person to decide.
 */
export function SourceComparison({ answer, onOpen }: SourceComparisonProps) {
  const comparison = answer.comparison;
  if (!comparison) return null;
  const columns = comparison.markers
    .map((marker) => ({ marker, passage: passageFor(answer, marker) }))
    .filter((c): c is { marker: number; passage: NonNullable<typeof c.passage> } => c.passage !== undefined);
  if (columns.length < 2) return null;

  return (
    <section aria-label="Sources differ" className="mt-4 rounded-xl border border-dashed bg-panel p-3">
      <h4 className="text-sm text-navy">Sources differ: {comparison.topic}</h4>
      <div className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {columns.map(({ marker, passage }) => (
          <article key={marker} aria-label={passage.source_title} className="flex flex-col rounded-lg border bg-card p-3">
            <div className="flex flex-wrap items-center gap-2">
              <CitationMarker marker={marker} heading={passage.heading} onOpen={onOpen} />
              <FlagChip tone={passage.label === "authoritative" ? "success" : "warning"}>{LABEL_TEXT[passage.label]}</FlagChip>
            </div>
            <div className="mt-1.5 text-sm font-semibold text-navy">{passage.source_title}</div>
            <div className="text-xs text-muted-foreground">{passage.heading}</div>
            <blockquote className="mt-2 border-l-2 border-gold pl-3 text-sm text-navy">{passage.text}</blockquote>
          </article>
        ))}
      </div>
    </section>
  );
}
