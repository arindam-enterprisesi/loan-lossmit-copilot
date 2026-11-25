import { ShowWorkingDrawer, type WorkingStep } from "@/components/shared/show-working-drawer";
import { StatCard } from "@/components/shared/stat-card";
import type { LenderFigure, LenderView as LenderViewData } from "@/lib/copilot-types";
import { LENDER_FIGURES, settingLabel, settingValue } from "@/lib/copilot";
import { formatMoney } from "@/lib/format";

/** "a + b = c" as one step: the sentence for the formula, the part before the last " = ", and the result. */
function stepOf(figure: LenderFigure): WorkingStep {
  const at = figure.working.lastIndexOf(" = ");
  const sentence = figure.formula.charAt(0).toUpperCase() + figure.formula.slice(1);
  return at >= 0
    ? { label: sentence, formula: figure.working.slice(0, at), result: figure.working.slice(at + 3) }
    : { label: sentence, formula: figure.working, result: formatMoney(figure.value) };
}

/**
 * The lender's position, shown first because loss mitigation exists mainly to protect the investor and the
 * servicer: the expected loss on foreclosure, the expected cost of the modification, and the difference. Every
 * figure comes from the backend with its working. The settings are illustrative and listed under the figures.
 * Final terms are never worked out here.
 */
export function LenderView({ view }: { view: LenderViewData }) {
  const values: Record<(typeof LENDER_FIGURES)[number]["key"], string> = {
    foreclosure_loss: view.foreclosure_loss,
    modification_cost: view.modification_cost,
    advantage: view.advantage,
  };
  return (
    <section aria-labelledby="lender-heading" className="space-y-3">
      <div>
        <h2 id="lender-heading" className="text-lg">
          Lender view
        </h2>
        <p className="text-xs text-muted-foreground">
          What each path is expected to cost the lender, from the illustrative settings below. A simplified comparison, not any investor&apos;s actual model.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {LENDER_FIGURES.map((f) => {
          const steps = f.chain.flatMap((name) => {
            const figure = view.figures.find((x) => x.name === name);
            return figure ? [stepOf(figure)] : [];
          });
          return (
            <div key={f.key} data-testid={`lender-${f.key}`} className="flex flex-col gap-3">
              <StatCard value={formatMoney(values[f.key])} label={f.label} className="flex-1" />
              {steps.length > 0 ? (
                <ShowWorkingDrawer
                  title={`Working: ${f.label}`}
                  steps={steps}
                  triggerAriaLabel={`Show working for ${f.label.toLowerCase()}`}
                  className="self-start"
                />
              ) : null}
            </div>
          );
        })}
      </div>
      <details className="rounded-xl border bg-card px-4 py-3 text-sm">
        <summary className="cursor-pointer text-sm font-semibold text-navy">Settings used (illustrative)</summary>
        <dl className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {Object.entries(view.settings).map(([key, value]) => (
            <div key={key}>
              <dt className="text-xs font-semibold text-muted-foreground">{settingLabel(key)}</dt>
              <dd className="text-navy">{settingValue(key, value)}</dd>
            </div>
          ))}
        </dl>
      </details>
      <p className="text-xs text-muted-foreground">{view.final_terms}</p>
    </section>
  );
}
