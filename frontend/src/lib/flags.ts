import type { Flag, Severity } from "@/lib/types";

/** One kind of flag on a document: its code, how serious it is, and every message that carried the code. */
export interface FlagGroup {
  code: string;
  severity: Severity;
  count: number;
  messages: string[];
}

const RANK: Record<Severity, number> = { error: 3, warning: 2, info: 1 };

/**
 * Groups flags that share a code, in the order each code first appears. The backend repeats one code for one kind of
 * problem found in several places (for example the "wasn't found in this document" code on each missing W-2 box), so a
 * code is not a unique key and a chip list would show the same code five times. The group keeps the most serious
 * severity and every message, so nothing is hidden.
 */
export function groupFlags(flags: readonly Flag[]): FlagGroup[] {
  const groups = new Map<string, FlagGroup>();
  for (const f of flags) {
    const existing = groups.get(f.code);
    if (!existing) {
      groups.set(f.code, { code: f.code, severity: f.severity, count: 1, messages: [f.message] });
      continue;
    }
    existing.count += 1;
    existing.messages.push(f.message);
    if ((RANK[f.severity] ?? 0) > (RANK[existing.severity] ?? 0)) existing.severity = f.severity;
  }
  return [...groups.values()];
}

/** The text on a grouped chip: the code, and how many times it was raised when more than once. */
export function flagGroupLabel(group: FlagGroup): string {
  return group.count > 1 ? `${group.code} ×${group.count}` : group.code;
}

/** A tooltip listing each message of a group, one per line. */
export function flagGroupTitle(group: FlagGroup): string {
  return group.messages.join("\n");
}
