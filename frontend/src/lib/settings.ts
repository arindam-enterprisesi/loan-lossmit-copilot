// Display helpers for the Settings screen. Words only: nothing here changes or works out a setting.
import type { ChipTone } from "@/components/shared/flag-chip";
import { humanize } from "./format";
import type { LlmTask, SettingLabel } from "./settings-types";

/** What each task is for, in the words a reviewer would use. A task not listed shows its name. */
export const TASK_PURPOSE: Record<string, string> = {
  smoke: "A quick check that the model answers",
  classify: "Finds each document's type",
  extract: "Reads the values from a document",
  label_transactions: "Labels bank transactions",
  hardship: "Reads the hardship letter",
  income_explain: "Writes the plain-language income notes",
  researcher: "Looks up the guidance for each finding",
  writer: "Drafts the report",
  critic: "Checks the draft against the evidence",
  guideline_answer: "Answers a guideline question from the passages found",
};

export const taskPurpose = (task: string): string => TASK_PURPOSE[task] ?? humanize(task);

export const LABEL_TEXT: Record<SettingLabel, string> = { illustrative: "Illustrative", authoritative: "Authoritative" };
export const LABEL_TONE: Record<SettingLabel, ChipTone> = { illustrative: "warning", authoritative: "success" };

/** The tasks in the order the backend lists them, with the ones on the default provider first being no different from the rest. */
export const sortedTasks = (tasks: LlmTask[]): LlmTask[] => [...tasks].sort((a, b) => a.task.localeCompare(b.task));

/** True for the one role that may see the settings. With the demo data nobody signs in, so everyone may. */
export const canSeeSettings = (role: string | null): boolean => role === null || role === "admin";
