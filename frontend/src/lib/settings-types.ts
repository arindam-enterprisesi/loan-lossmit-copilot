// Types for the Settings screen (administrator, read-only): which model answers each task, and the version
// and label of every setting file (CLAUDE.md rule 4: every setting is versioned and labelled illustrative or
// authoritative).
//
// The backend has no endpoint for this yet. The mock reads like the backend's own files: backend/config/llm.yaml
// for the models and the `version` and `label` at the top of each file in backend/config for the rest. The
// shape below is my proposal for `GET /settings`; Arindam owns the model settings (backend/app/llm) and Abhay
// the other files, and this is read-only until one of them adds a way to change a value.

export type SettingLabel = "illustrative" | "authoritative";

/** One kind of work the system asks a model to do, and which provider and model currently does it. */
export interface LlmTask {
  /** The name in llm.yaml, such as "classify". */
  task: string;
  provider: string;
  model: string;
}

/** A provider the system can use, and the model it uses with it. */
export interface LlmProvider {
  name: string;
  model: string;
}

export interface LlmSettings {
  version: string;
  label: SettingLabel;
  /** The provider a task uses unless it says otherwise. */
  default_provider: string;
  providers: LlmProvider[];
  tasks: LlmTask[];
  /** The model that turns text into search vectors. Null when the backend does not say. */
  embeddings: { provider: string; model: string } | null;
}

/** One settings file: what it holds, its version and whether its values are illustrative or authoritative. */
export interface ConfigVersion {
  /** For example "thresholds.yaml". */
  name: string;
  /** What the values in it are used for, in a sentence. */
  used_for: string;
  version: string;
  label: SettingLabel;
}

export interface Settings {
  llm: LlmSettings;
  config: ConfigVersion[];
}
