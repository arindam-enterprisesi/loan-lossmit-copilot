// Small pure helpers for the page viewer: zoom steps, page limits and where to draw each field's box.
// Boxes come from the API as fractions of the page (0 to 1), so they stay right at any zoom.
import type { CSSProperties } from "react";
import { fieldLabel } from "@/lib/documents";
import type { BoundingBox, Field } from "@/lib/types";

export const ZOOM_STEPS = [0.5, 0.75, 1, 1.5, 2, 3] as const;
export const DEFAULT_ZOOM = 1;

/** The next zoom level up (1) or down (-1), staying inside the allowed range. */
export function stepZoom(current: number, direction: 1 | -1): number {
  let nearest = 0;
  ZOOM_STEPS.forEach((z, i) => {
    if (Math.abs(z - current) < Math.abs(ZOOM_STEPS[nearest] - current)) nearest = i;
  });
  const next = Math.min(ZOOM_STEPS.length - 1, Math.max(0, nearest + direction));
  return ZOOM_STEPS[next];
}

/** Keeps a page number between 1 and the page count. */
export function clampPage(page: number, pageCount: number): number {
  return Math.min(Math.max(1, pageCount), Math.max(1, page));
}

/** CSS that places a 0-to-1 box over the page as percentages. */
export function boxStyle(b: BoundingBox): CSSProperties {
  return {
    left: `${b.x0 * 100}%`,
    top: `${b.y0 * 100}%`,
    width: `${(b.x1 - b.x0) * 100}%`,
    height: `${(b.y1 - b.y0) * 100}%`,
  };
}

/** One field's place on a page. */
export interface ViewerBox {
  name: string;
  label: string;
  page: number;
  bbox: BoundingBox;
}

/** Every field that has a box on the page. Fields without a box are simply not drawn. */
export function boxesFromFields(fields: Field[]): ViewerBox[] {
  return fields.flatMap((f) =>
    f.evidence?.bbox
      ? [{ name: f.name, label: fieldLabel(f.name), page: f.evidence.page, bbox: f.evidence.bbox }]
      : [],
  );
}

/** How many pages the arrows can reach: the document's page count, or the highest page any field points to. */
export function pageCountFor(pageCount: number | null | undefined, fields: Field[]): number {
  const highest = Math.max(1, ...fields.map((f) => f.evidence?.page ?? 1));
  return Math.max(pageCount ?? 1, highest);
}
