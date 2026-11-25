"use client";

import { useId, useState } from "react";
import { SELECT_CLASS } from "@/components/documents/select-class";
import { ErrorNotice } from "@/components/shared/error-notice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LOAN_PURPOSES, OCCUPANCIES, optionsWith, validateScenario, type ScenarioErrors } from "@/lib/assets";
import type { LoanScenario, LoanScenarioInput } from "@/lib/assets-types";
import { formatDate } from "@/lib/format";

interface LoanScenarioFormProps {
  /** The saved scenario, or null when none has been entered yet. */
  scenario: LoanScenario | null;
  /**
   * Saves the scenario. If it throws, the form shows the message and keeps what was typed.
   */
  onSave: (input: LoanScenarioInput) => Promise<void>;
}

const EMPTY: LoanScenarioInput = {
  purpose: "",
  occupancy: "",
  property_value: "",
  loan_amount: "",
  proposed_housing_payment: "",
  funds_to_close: "",
};

const MONEY_FIELDS: { key: "property_value" | "loan_amount" | "proposed_housing_payment" | "funds_to_close"; label: string }[] = [
  { key: "property_value", label: "Property value" },
  { key: "loan_amount", label: "Loan amount" },
  { key: "proposed_housing_payment", label: "Proposed monthly housing payment" },
  { key: "funds_to_close", label: "Funds needed to close" },
];

/** One labelled box. The message is beside the label, not inside it, so the box's name never changes. */
function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: (props: { id: string; "aria-invalid"?: true; "aria-describedby"?: string }) => React.ReactNode;
}) {
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-semibold text-muted-foreground">
        {label}
      </label>
      {children({ id, "aria-invalid": error ? true : undefined, "aria-describedby": error ? errorId : undefined })}
      {error ? (
        <span id={errorId} className="text-xs text-danger">
          {error}
        </span>
      ) : null}
    </div>
  );
}

/**
 * The sample loan, entered by hand (Feature Design 3.3). Nothing is priced and nothing is worked out here:
 * the backend does every ratio. The same rules the backend applies are checked before sending, so a
 * mistake is named next to its box. Mount it with `key={caseId}` so it starts fresh for each case.
 */
export function LoanScenarioForm({ scenario, onSave }: LoanScenarioFormProps) {
  const [values, setValues] = useState<LoanScenarioInput>(() =>
    scenario
      ? {
          purpose: scenario.purpose,
          occupancy: scenario.occupancy,
          property_value: scenario.property_value,
          loan_amount: scenario.loan_amount,
          proposed_housing_payment: scenario.proposed_housing_payment,
          funds_to_close: scenario.funds_to_close,
        }
      : EMPTY,
  );
  const [errors, setErrors] = useState<ScenarioErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [changed, setChanged] = useState(false);

  const set = (key: keyof LoanScenarioInput, value: string) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
    setChanged(true);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (saving) return;
    const found = validateScenario(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(values);
      setChanged(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "The loan scenario could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} aria-label="Loan scenario" className="rounded-xl border bg-card p-4" noValidate>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg">Loan scenario</h2>
        <span className="text-xs text-muted-foreground">
          {scenario?.updated_at ? `Saved ${formatDate(scenario.updated_at)}` : scenario ? "Saved" : "Not saved yet"}
        </span>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        The sample loan, entered by hand. Nothing is priced. Save it, then run the analysis.
      </p>

      {saveError ? <ErrorNotice message={saveError} className="mt-3" /> : null}

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Loan purpose" error={errors.purpose}>
          {(a11y) => (
            <select className={SELECT_CLASS} value={values.purpose} onChange={(e) => set("purpose", e.target.value)} {...a11y}>
              <option value="">Choose…</option>
              {optionsWith(LOAN_PURPOSES, values.purpose).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          )}
        </Field>

        <Field label="Occupancy" error={errors.occupancy}>
          {(a11y) => (
            <select className={SELECT_CLASS} value={values.occupancy} onChange={(e) => set("occupancy", e.target.value)} {...a11y}>
              <option value="">Choose…</option>
              {optionsWith(OCCUPANCIES, values.occupancy).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          )}
        </Field>

        {MONEY_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} error={errors[f.key]}>
            {(a11y) => (
              <Input inputMode="decimal" value={values[f.key]} onChange={(e) => set(f.key, e.target.value)} placeholder="0.00" {...a11y} />
            )}
          </Field>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save scenario"}
        </Button>
        {changed ? <span className="text-xs text-muted-foreground">Not saved yet.</span> : null}
      </div>
    </form>
  );
}
