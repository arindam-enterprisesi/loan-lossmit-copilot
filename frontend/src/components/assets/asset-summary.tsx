import { FlagChip } from "@/components/shared/flag-chip";
import { ShowWorkingDrawer } from "@/components/shared/show-working-drawer";
import { CANDIDATE_RATIO_LABEL, figureText } from "@/lib/assets";
import type { AssetAnalysis, AssetFigure } from "@/lib/assets-types";
import { workingEvidence } from "@/lib/income";

interface AssetSummaryProps {
  analysis: AssetAnalysis;
  pillarSlug: string;
}

function Working({ title, figure, analysis, pillarSlug }: { title: string; figure: AssetFigure; analysis: AssetAnalysis; pillarSlug: string }) {
  return (
    <ShowWorkingDrawer
      title={title}
      steps={figure.working}
      evidence={workingEvidence(figure.evidence, pillarSlug, analysis.case_id)}
      triggerAriaLabel={`Show working for ${title}`}
    />
  );
}

function Card({
  id,
  label,
  figure,
  analysis,
  pillarSlug,
  children,
}: {
  id: string;
  label: string;
  figure: AssetFigure | null;
  analysis: AssetAnalysis;
  pillarSlug: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-xl border bg-panel p-5" data-testid={`figure-${id}`}>
      <div className="text-sm font-semibold text-navy">{label}</div>
      <div className="mt-1 font-heading text-3xl font-bold text-teal">{figureText(figure)}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{figure ? CANDIDATE_RATIO_LABEL : "Cannot be worked out yet. See the flags below."}</div>
      {children}
      {figure ? (
        <div className="mt-3">
          <Working title={label} figure={figure} analysis={analysis} pillarSlug={pillarSlug} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * The summary strip: documented assets, funds to close with the shortfall, front-end ratio, DTI and LTV.
 * Every figure is shown exactly as the backend returned it, with its working, and is labelled as a
 * candidate for the underwriter to review. A person decides what counts.
 */
export function AssetSummary({ analysis, pillarSlug }: AssetSummaryProps) {
  const dtiFlag = analysis.flags.some((f) => f.code === "AL-W106" && f.status !== "resolved");
  return (
    <div className="space-y-4">
      <section aria-label="Summary" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Card id="documented_assets" label="Documented assets" figure={analysis.documented_assets} analysis={analysis} pillarSlug={pillarSlug} />

        <Card id="funds_to_close" label="Funds to close" figure={analysis.funds_to_close} analysis={analysis} pillarSlug={pillarSlug}>
          {analysis.funds_shortfall ? (
            <div className="mt-2 rounded-lg border bg-card px-3 py-2" data-testid="figure-funds_shortfall">
              <div className="text-xs font-semibold text-muted-foreground">Shortfall</div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-base font-semibold text-navy">{figureText(analysis.funds_shortfall)}</span>
                <Working title="Shortfall" figure={analysis.funds_shortfall} analysis={analysis} pillarSlug={pillarSlug} />
              </div>
            </div>
          ) : null}
        </Card>

        <Card id="front_end_ratio" label="Front-end ratio" figure={analysis.front_end_ratio} analysis={analysis} pillarSlug={pillarSlug} />

        <Card id="dti" label="DTI" figure={analysis.dti} analysis={analysis} pillarSlug={pillarSlug}>
          {dtiFlag ? (
            <div className="mt-2">
              <FlagChip tone="warning">Above the review level</FlagChip>
            </div>
          ) : null}
        </Card>

        <Card id="ltv" label="LTV" figure={analysis.ltv} analysis={analysis} pillarSlug={pillarSlug} />
      </section>

      {analysis.other_figures.length > 0 ? (
        <section aria-label="Other figures" className="rounded-xl border bg-card px-4 py-3">
          <h3 className="text-sm text-navy">Other figures, to test</h3>
          <ul className="mt-2 divide-y">
            {analysis.other_figures.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center justify-between gap-3 py-2" data-testid={`other-${o.id}`}>
                <div>
                  <div className="text-sm font-semibold text-navy">{o.label}</div>
                  <div className="text-xs text-muted-foreground">
                    {CANDIDATE_RATIO_LABEL}. Whether it counts is a decision for a person.
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-heading text-xl font-bold text-teal">{figureText(o.figure)}</span>
                  <Working title={o.label} figure={o.figure} analysis={analysis} pillarSlug={pillarSlug} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
