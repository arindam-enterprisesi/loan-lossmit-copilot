import type { FieldReview } from "./types";

export type ReviewAction = FieldReview["action"];

export interface ReviewInput {
  value?: string;
  reason?: string;
}

export type ReviewResult =
  | { ok: true; review: FieldReview }
  | { ok: false; errors: { value?: string; reason?: string } };

/**
 * Builds the PATCH body for a field review and applies the contract rules: "correct" needs a value
 * and a reason, "reject" needs a reason, "confirm" needs neither. `expected_version` is always sent
 * so a stale edit is refused (409) instead of overwriting someone else's change.
 */
export function buildReview(
  action: ReviewAction,
  input: ReviewInput,
  expectedVersion: number,
): ReviewResult {
  const value = input.value?.trim() ?? "";
  const reason = input.reason?.trim() ?? "";

  if (action === "confirm") {
    return { ok: true, review: { action, expected_version: expectedVersion } };
  }

  const errors: { value?: string; reason?: string } = {};
  if (action === "correct" && !value) errors.value = "Enter the corrected value.";
  if (!reason) errors.reason = "Give a reason. It is kept with the change.";
  if (errors.value || errors.reason) return { ok: false, errors };

  return {
    ok: true,
    review:
      action === "correct"
        ? { action, value, reason, expected_version: expectedVersion }
        : { action, reason, expected_version: expectedVersion },
  };
}
