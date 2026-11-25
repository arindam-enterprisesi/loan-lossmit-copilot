import { EmptyState } from "./empty-state";

/** What a screen that works on one case shows when there is no case to work on: a sentence, not a blank page. */
export function NoCases() {
  return (
    <EmptyState title="No cases yet">
      There is no case to show here. Cases appear once one has been created, and then each screen in the menu works on one of them.
    </EmptyState>
  );
}
