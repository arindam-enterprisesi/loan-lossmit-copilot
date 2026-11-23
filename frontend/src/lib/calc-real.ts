// Shared by the files that read the real backend's answers (hardship-real.ts, assets-real.ts, and next
// the income and completeness ones). The backend sends every figure as a "calculation": a value, a
// formula, and its working as one line of text ending in "= result". These turn that into what the
// screens show. Nothing here calculates (CLAUDE.md rule 1).
import type { WorkingStep } from "@/components/shared/show-working-drawer";
import { humanize } from "./format";
import type { EvidenceLink } from "./income-types";

/** A figure's source: a line of a document, or a hand-entered value or another calculation. */
export interface RealRef {
  document_id?: string | null;
  field?: string | null;
  line_ids: string[];
  source?: string | null;
  calculation?: string | null;
}

export interface RealCalc {
  id: string;
  name: string;
  value: string;
  unit: string;
  formula: string;
  inputs: Record<string, string>;
  /** One line of text, ending in "= result", e.g. "1,720.00 / 4,200.00 = 40.95%". */
  working: string;
  config_version: string;
  evidence: RealRef[];
}

/** "Regular monthly payment", linked to its document and lines when the backend names them. */
export const evidenceOf = (refs: RealRef[]): EvidenceLink[] =>
  refs.map((r) => ({
    label: humanize(r.field ?? r.source ?? r.calculation ?? "source"),
    document_id: r.document_id ?? undefined,
    line_ids: r.line_ids,
  }));

/** The percentage the backend wrote at the end of its working ("... = 40.95%"), without the % sign. */
export function percentFromWorking(working: string): string | null {
  const m = /=\s*(-?\d[\d,]*(?:\.\d+)?)%\s*$/.exec(working);
  return m ? m[1] : null;
}

/** "a + b = c" -> one step: the sentence for the formula, the part before the last " = ", and the result. */
export function stepOf(calc: RealCalc): WorkingStep {
  const at = calc.working.lastIndexOf(" = ");
  const sentence = calc.formula.charAt(0).toUpperCase() + calc.formula.slice(1);
  return at >= 0
    ? { label: sentence, formula: calc.working.slice(0, at), result: calc.working.slice(at + 3) }
    : { label: sentence, formula: calc.working, result: calc.value };
}

export type FigureUnit = "money" | "percent";

/**
 * The value to show. A ratio is shown as the backend's own percentage text; if that text is missing
 * the ratio is shown as it came, never multiplied here.
 */
export function shownValue(calc: RealCalc): { value: string; unit: FigureUnit } {
  if (calc.unit === "ratio") {
    const percent = percentFromWorking(calc.working);
    return percent ? { value: percent, unit: "percent" } : { value: calc.value, unit: "money" };
  }
  return { value: calc.value, unit: "money" };
}
