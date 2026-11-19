"use client";

import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { boxStyle, clampPage, DEFAULT_ZOOM, stepZoom, ZOOM_STEPS, type ViewerBox } from "@/lib/viewer";
import { cn } from "@/lib/utils";

interface PageViewerProps {
  title?: string;
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  /** Short-lived page image URL. Without it a blank page placeholder is drawn. */
  imageUrl?: string;
  /** Every field's box, across all pages. Only the current page's boxes are drawn. */
  boxes: ViewerBox[];
  selectedName: string | null;
  hoveredName: string | null;
  onSelect: (name: string) => void;
  onHover: (name: string | null) => void;
  /** The browser could not load the image (for example an expired link). The parent can fetch a fresh one. */
  onImageError?: () => void;
  /** The image loaded fine. */
  onImageLoad?: () => void;
  /** Line IDs of the selected field, shown under the page. */
  lineIds: string[];
  className?: string;
}

/**
 * The document page with every field's box drawn over it. Pick a box to select its field, hover to
 * light it up. Zoom and page buttons let the reviewer read small print. Boxes are fractions of the
 * page, so they stay on the right spot at any zoom.
 */
export function PageViewer({
  title = "Evidence",
  page,
  pageCount,
  onPageChange,
  imageUrl,
  boxes,
  selectedName,
  hoveredName,
  onSelect,
  onHover,
  onImageError,
  onImageLoad,
  lineIds,
  className,
}: PageViewerProps) {
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const pageBoxes = boxes.filter((b) => b.page === page);
  const atMin = zoom <= ZOOM_STEPS[0];
  const atMax = zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1];

  return (
    <aside className={cn("rounded-xl border bg-card p-4", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-heading text-base">{title}</h3>
        <span className="text-xs text-muted-foreground">
          Page {page} of {pageCount}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            aria-label="Previous page"
            disabled={page <= 1}
            onClick={() => onPageChange(clampPage(page - 1, pageCount))}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            aria-label="Next page"
            disabled={page >= pageCount}
            onClick={() => onPageChange(clampPage(page + 1, pageCount))}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            aria-label="Zoom out"
            disabled={atMin}
            onClick={() => setZoom((z) => stepZoom(z, -1))}
          >
            <Minus className="size-4" />
          </Button>
          <span data-testid="zoom-level" className="w-12 text-center text-xs tabular-nums text-muted-foreground">
            {Math.round(zoom * 100)}%
          </span>
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            aria-label="Zoom in"
            disabled={atMax}
            onClick={() => setZoom((z) => stepZoom(z, 1))}
          >
            <Plus className="size-4" />
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setZoom(DEFAULT_ZOOM)}>
            Reset zoom
          </Button>
        </div>
      </div>

      <div data-testid="page-frame" className="mt-3 max-h-[75vh] overflow-auto rounded-md border bg-panel">
        <div
          data-testid="page-canvas"
          className="relative aspect-[8.5/11] bg-panel"
          style={{ width: `${zoom * 100}%` }}
        >
          {imageUrl ? (
            // Presigned S3 URL that changes every 5 minutes: next/image optimisation does not help here.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imageUrl}
              alt={`Page ${page}`}
              onError={onImageError}
              onLoad={onImageLoad}
              className="absolute inset-0 size-full object-contain"
            />
          ) : (
            <div className="absolute inset-0 flex flex-col gap-2 p-4" aria-hidden>
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="h-2 rounded bg-border" style={{ width: `${55 + ((i * 17) % 40)}%` }} />
              ))}
            </div>
          )}
          {pageBoxes.map((b) => {
            const selected = b.name === selectedName;
            const hovered = b.name === hoveredName;
            return (
              <button
                key={b.name}
                type="button"
                // The selected box keeps the old test id so existing checks on "the" box still work.
                data-testid={selected ? "evidence-box" : "field-box"}
                data-field={b.name}
                aria-label={`Show ${b.label} on the page`}
                aria-pressed={selected}
                onClick={() => onSelect(b.name)}
                onMouseEnter={() => onHover(b.name)}
                onMouseLeave={() => onHover(null)}
                onFocus={() => onHover(b.name)}
                onBlur={() => onHover(null)}
                className={cn(
                  "absolute rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selected
                    ? "z-10 border-2 border-gold bg-gold/25"
                    : hovered
                      ? "z-10 border-2 border-teal bg-teal/20"
                      : "border border-teal/50 bg-transparent",
                )}
                style={boxStyle(b.bbox)}
              />
            );
          })}
        </div>
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
