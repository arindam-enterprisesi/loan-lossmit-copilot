"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { FlagChip } from "@/components/shared/flag-chip";
import { ReasonDialog } from "@/components/shared/reason-dialog";
import { Button } from "@/components/ui/button";
import type { OverrideRequest, OverrideStatus, WaterfallCondition, WaterfallOption } from "@/lib/copilot-types";
import {
  conditionValue,
  OPTION_LABEL,
  OVERRIDE_STATUS_OPTIONS,
  REASON_MAX,
  valueLabel,
  WATERFALL_STATUS_LABEL,
  WATERFALL_STATUS_TONE,
  waterfallCards,
  type WaterfallCard,
} from "@/lib/copilot";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface WaterfallProps {
  options: WaterfallOption[];
  /** Overrides one condition. A failure is thrown, so the window can show it and keep what was typed. */
  onOverride: (conditionId: string, req: OverrideRequest) => Promise<void>;
  onOpenPassage: (passageId: string) => void;
}

/**
 * The options in the investor's order. The rules stop at the first option whose conditions are met, so the ones
 * after it are greyed as not reached. Each card expands to its conditions, the values the rules used and the passage
 * of the investor guide each rule comes from. "Met" says the conditions are met and nothing more. A person can
 * override a condition with a reason: the statuses recompute, and the rules' own status stays visible beside it.
 */
export function Waterfall({ options, onOverride, onOpenPassage }: WaterfallProps) {
  const [overriding, setOverriding] = useState<WaterfallCondition | null>(null);
  const cards = waterfallCards(options);

  return (
    <section aria-labelledby="waterfall-heading" className="space-y-3">
      <div>
        <h2 id="waterfall-heading" className="text-lg">
          Waterfall
        </h2>
        <p className="text-xs text-muted-foreground">
          The rules are applied in order and stop at the first option whose conditions are met. {"\"Met\" says only that an option's conditions are met. It is not a decision."}
        </p>
      </div>
      <ol aria-label="Options in waterfall order" className="space-y-3">
        {cards.map((card) => (
          <OptionCard key={card.key} card={card} onOverride={setOverriding} onOpenPassage={onOpenPassage} />
        ))}
      </ol>

      {overriding ? (
        <ReasonDialog
          open
          onOpenChange={(open) => {
            if (!open) setOverriding(null);
          }}
          title="Override this condition"
          description="Set the status you judge it to have. The rules' own status stays beside your override, and the options are recomputed."
          note={`${overriding.label}. The rules found: ${WATERFALL_STATUS_LABEL[overriding.status]}.`}
          confirmLabel="Save override"
          maxLength={REASON_MAX}
          field={{
            label: "Status",
            initialValue: overriding.effective_status === "not_reached" ? "met" : overriding.effective_status,
            options: OVERRIDE_STATUS_OPTIONS,
            validate: (v) => (v === overriding.effective_status ? "Pick a different status from the one shown now." : null),
          }}
          onConfirm={(reason, value) => onOverride(overriding.id, { status: value as OverrideStatus, reason })}
        />
      ) : null}
    </section>
  );
}

interface OptionCardProps {
  card: WaterfallCard;
  onOverride: (condition: WaterfallCondition) => void;
  onOpenPassage: (passageId: string) => void;
}

function OptionCard({ card, onOverride, onOpenPassage }: OptionCardProps) {
  const [open, setOpen] = useState(false);
  const panelId = `conditions-${card.key}`;
  const overridden = card.options.some((o) => o.overridden);
  const greyed = card.status === "not_reached";

  return (
    <li
      data-testid={`option-${card.key}`}
      data-status={card.status}
      className={cn("rounded-xl border p-4", greyed ? "bg-panel text-muted-foreground" : "bg-card")}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span
          aria-hidden
          className="flex h-7 min-w-7 shrink-0 items-center justify-center rounded-full bg-panel px-1.5 text-xs font-semibold whitespace-nowrap tabular-nums text-muted-foreground ring-1 ring-inset ring-border"
        >
          {card.position}
        </span>
        <h3 className={cn("text-base", greyed ? "text-muted-foreground" : "text-navy")}>{card.title}</h3>
        <FlagChip tone={WATERFALL_STATUS_TONE[card.status]}>{WATERFALL_STATUS_LABEL[card.status]}</FlagChip>
        {overridden ? <FlagChip tone="info">Overridden</FlagChip> : null}
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          aria-expanded={open}
          aria-controls={panelId}
          aria-label={`${open ? "Hide" : "Show"} conditions for ${card.title}`}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
          Conditions
        </Button>
      </div>

      {open ? (
        <div id={panelId} className="mt-3 space-y-4">
          {card.options.map((o) => (
            <div key={o.option} className="space-y-2">
              {card.options.length > 1 ? <h4 className="text-sm font-semibold text-navy">{OPTION_LABEL[o.option]}</h4> : null}
              <ul className="space-y-2">
                {o.conditions.map((c) => (
                  <ConditionRow key={c.id} condition={c} onOverride={onOverride} onOpenPassage={onOpenPassage} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function ConditionRow({ condition: c, onOverride, onOpenPassage }: { condition: WaterfallCondition } & Omit<OptionCardProps, "card">) {
  const values = Object.entries(c.values);
  return (
    <li data-testid={`condition-${c.id}`} className="space-y-1.5 rounded-lg border bg-card px-3 py-2 text-navy">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{c.label}</span>
        <FlagChip tone={WATERFALL_STATUS_TONE[c.effective_status]}>{WATERFALL_STATUS_LABEL[c.effective_status]}</FlagChip>
      </div>
      <code className="block text-xs text-muted-foreground">{c.expression}</code>

      {values.length > 0 ? (
        <dl aria-label="Values used" className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {values.map(([key, value]) => (
            <div key={key} className="flex gap-1.5">
              <dt className="text-muted-foreground">{valueLabel(key)}:</dt>
              <dd className="font-medium tabular-nums">{conditionValue(key, value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {c.derived ? <p className="text-xs text-muted-foreground">Follows from the options before it. It is not set by a person.</p> : null}

      {c.override ? (
        <p className="rounded-lg bg-panel px-3 py-2 text-xs text-muted-foreground">
          <span className="font-semibold">Overridden.</span> The rules found {WATERFALL_STATUS_LABEL[c.status]}; now {WATERFALL_STATUS_LABEL[c.override.status]}. By{" "}
          {c.override.by} on {formatDate(c.override.at)}. Reason: {c.override.reason}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2 pt-0.5">
        {c.passage_id ? (
          <Button variant="outline" size="sm" aria-label={`Open the cited passage for ${c.label}`} onClick={() => onOpenPassage(c.passage_id!)}>
            Cited passage
          </Button>
        ) : null}
        {!c.derived ? (
          <Button variant="outline" size="sm" aria-label={`Override ${c.label}`} onClick={() => onOverride(c)}>
            Override
          </Button>
        ) : null}
      </div>
    </li>
  );
}
