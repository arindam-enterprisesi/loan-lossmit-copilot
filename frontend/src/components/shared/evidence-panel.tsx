import { cn } from "@/lib/utils";
import type { BoundingBox } from "@/lib/types";

interface EvidencePanelProps {
  title?: string;
  page: number;
  lineIds: string[];
  /** Box as fractions of the page (0 to 1), straight from the API. */
  bbox?: BoundingBox;
  /** Short-lived presigned page image URL. Without it a blank page placeholder is drawn. */
  imageUrl?: string;
  className?: string;
}

/**
 * Evidence side panel: the page image with the cited box drawn over it. Boxes are fractions of the
 * page, so they stay correct at any display size.
 */
export function EvidencePanel({
  title = "Evidence",
  page,
  lineIds,
  bbox,
  imageUrl,
  className,
}: EvidencePanelProps) {
  return (
    <aside className={cn("rounded-xl border bg-card p-4", className)}>
      <div className="flex items-baseline justify-between">
        <h3 className="font-heading text-base">{title}</h3>
        <span className="text-xs text-muted-foreground">Page {page}</span>
      </div>
      <div className="relative mt-3 aspect-[8.5/11] w-full overflow-hidden rounded-md border bg-panel">
        {imageUrl ? (
          // Presigned S3 URL that changes every 5 minutes: next/image optimisation does not help here.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={imageUrl} alt={`Page ${page}`} className="absolute inset-0 size-full object-contain" />
        ) : (
          <div className="absolute inset-0 flex flex-col gap-2 p-4" aria-hidden>
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="h-2 rounded bg-border" style={{ width: `${55 + ((i * 17) % 40)}%` }} />
            ))}
          </div>
        )}
        {bbox ? (
          <div
            data-testid="evidence-box"
            className="absolute rounded-sm border-2 border-gold bg-gold/25"
            style={{
              left: `${bbox.x0 * 100}%`,
              top: `${bbox.y0 * 100}%`,
              width: `${(bbox.x1 - bbox.x0) * 100}%`,
              height: `${(bbox.y1 - bbox.y0) * 100}%`,
            }}
          />
        ) : null}
      </div>
      {lineIds.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {lineIds.map((id) => (
            <code key={id} className="rounded bg-panel px-1.5 py-0.5 text-xs text-navy">
              {id}
            </code>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
