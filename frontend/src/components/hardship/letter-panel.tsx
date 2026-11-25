import Link from "next/link";
import { documentHref } from "@/lib/income";
import { splitLine } from "@/lib/hardship";
import type { HardshipLetter, ProfileItem, ProfileKey } from "@/lib/hardship-types";
import { cn } from "@/lib/utils";

interface LetterPanelProps {
  letter: HardshipLetter;
  profile: ProfileItem[];
  caseId: string;
  pillarSlug: string;
  /** The profile item whose quote is shown strongly. The other quotes stay lightly highlighted. */
  selectedKey: ProfileKey | null;
  /** The profile item under the pointer (or with the keyboard focus). Its lines light up while it is. */
  hoveredKey?: ProfileKey | null;
}

/** The hardship letter line by line, with each profile item's quote highlighted in place. */
export function LetterPanel({ letter, profile, caseId, pillarSlug, selectedKey, hoveredKey = null }: LetterPanelProps) {
  // Pointing at an item wins over the one picked with "Show in letter", until the pointer leaves.
  const activeKey = hoveredKey ?? selectedKey;
  const activeLines = new Set(profile.find((i) => i.key === activeKey)?.quote?.line_ids ?? []);

  return (
    <section aria-labelledby="letter-heading" className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="letter-heading" className="text-base text-navy">
          Hardship letter
        </h3>
        {letter.document_id ? (
          <Link
            href={documentHref(pillarSlug, caseId, letter.document_id)}
            className="text-xs text-muted-foreground underline underline-offset-2"
          >
            Open the document
          </Link>
        ) : null}
      </div>
      {letter.partial ? (
        <p className="mt-1 text-xs text-warning">
          Only the quoted lines are shown. The whole letter appears here once the backend can return its text.
        </p>
      ) : null}
      <p className="mt-1 text-xs text-muted-foreground">
        Highlighted text is what each item on the right was read from.
      </p>
      <ol className="mt-3 space-y-1.5">
        {letter.lines.map((line) => (
          <li
            key={line.id}
            id={`letter-${line.id}`}
            data-active={activeLines.has(line.id) ? "true" : undefined}
            className={cn(
              "grid grid-cols-[3.25rem_1fr] gap-3 rounded px-1 text-sm transition-colors",
              activeLines.has(line.id) && "bg-gold/10",
            )}
          >
            <span className="pt-0.5 font-mono text-xs text-muted-foreground">{line.id}</span>
            <span className="text-navy">
              {splitLine(line.id, line.text, profile).map((segment, i) =>
                segment.key ? (
                  <mark
                    key={i}
                    data-quote={segment.key}
                    className={cn(
                      "rounded px-0.5 text-navy",
                      segment.key === selectedKey || segment.key === hoveredKey ? "bg-gold/50 ring-1 ring-gold" : "bg-gold/20",
                    )}
                  >
                    {segment.text}
                  </mark>
                ) : (
                  <span key={i}>{segment.text}</span>
                ),
              )}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
