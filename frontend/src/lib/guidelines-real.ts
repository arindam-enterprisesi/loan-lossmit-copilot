// Reads the real backend's guideline answers into the shapes the Guideline assistant uses. The real
// shapes are in backend/app/api/routers/guidelines.py (on `main` since PR #12): GET /guidelines/sources
// and GET /guidelines/passages/{id}. They are read-only, and are not in contracts/openapi.yaml.
//
// The ask endpoint is not on `main`, so there is nothing to translate for an answer yet: its shape is the
// proposal in guidelines-types.ts. This file only renames fields. It changes nothing about the text.
import type { GuidelinePassage, GuidelineSource, PassageLabel } from "./guidelines-types";

export interface RealSource {
  id: string;
  title: string;
  kind: string;
  label: string;
  passage_count: number;
}

export interface RealPassage {
  id: string;
  source_id: string;
  source_title: string;
  heading: string;
  text: string;
  label: string;
  /** e.g. "Seeded sample: an invented illustrative passage, not an investor's real guide." */
  notice: string;
}

/** Anything the backend labels other than "authoritative" is shown as illustrative, the cautious reading. */
const labelOf = (label: string): PassageLabel => (label === "authoritative" ? "authoritative" : "illustrative");

export const toGuidelineSource = (s: RealSource): GuidelineSource => ({
  id: s.id,
  title: s.title,
  kind: s.kind,
  label: labelOf(s.label),
  passage_count: s.passage_count,
});

export const toGuidelinePassage = (p: RealPassage): GuidelinePassage => ({
  id: p.id,
  source_id: p.source_id,
  source_title: p.source_title,
  heading: p.heading,
  text: p.text,
  label: labelOf(p.label),
  // The backend does not send a page or a version yet.
  page: null,
  version: null,
  notice: p.notice || null,
});
