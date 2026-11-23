import { FlagChip } from "@/components/shared/flag-chip";
import type { RuleSet } from "@/lib/copilot-types";

/**
 * Which rule set the waterfall used, and whether it is real. The rules here are invented for the demo, so the
 * banner says so every time: "Illustrative - Sample Investor A v1", and "not an actual investor's requirements".
 */
export function RuleSetBanner({ ruleSet }: { ruleSet: RuleSet }) {
  const illustrative = ruleSet.label === "illustrative";
  return (
    <div
      role="note"
      data-testid="rule-set-banner"
      className={
        illustrative
          ? "flex flex-wrap items-center gap-3 rounded-xl border-2 border-gold/60 bg-gold/10 px-4 py-3 text-sm text-navy"
          : "flex flex-wrap items-center gap-3 rounded-xl border bg-card px-4 py-3 text-sm text-navy"
      }
    >
      <FlagChip tone={illustrative ? "warning" : "success"}>{illustrative ? "Illustrative" : "Authoritative"}</FlagChip>
      <span className="font-semibold">
        {illustrative ? "Illustrative" : "Authoritative"} - {ruleSet.name} v{ruleSet.version}
      </span>
      {ruleSet.banner ? <span className="text-muted-foreground">{ruleSet.banner}</span> : null}
    </div>
  );
}
