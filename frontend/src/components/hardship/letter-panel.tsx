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
}

/** The hardship letter line by line, with each profile item's quote highlighted in place. */
export function LetterPanel({ letter, profile, caseId, pillarSlug, selectedKey }: LetterPanelProps) {
  return (
    <section aria-labelledby="letter-heading" className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="letter-heading" className="text-base text-navy">
          Hardship letter
        </h3>
        <Link
          href={documentHref(pillarSlug, caseId, letter.document_id)}
          className="text-xs text-muted-foreground underline underline-offset-2"
        >
          Open the document
        </Link>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Highlighted text is what each item on the right was read from.
      </p>
      <ol className="mt-3 space-y-1.5">
        {letter.lines.map((line) => (
          <li key={line.id} id={`letter-${line.id}`} className="grid grid-cols-[3.25rem_1fr] gap-3 text-sm">
            <span className="pt-0.5 font-mono text-xs text-muted-foreground">{line.id}</span>
            <span className="text-navy">
              {splitLine(line.id, line.text, profile).map((segment, i) =>
                segment.key ? (
                  <mark
                    key={i}
                    data-quote={segment.key}
                    className={cn(
                      "rounded px-0.5 text-navy",
                      segment.key === selectedKey ? "bg-gold/50 ring-1 ring-gold" : "bg-gold/20",
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
