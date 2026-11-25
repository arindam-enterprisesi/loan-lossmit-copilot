// Translation of the settings answer into the screen's shape. There is no such endpoint on `main` yet, so this
// follows my proposal for `GET /settings`: the model settings as maps (as llm.yaml writes them) and the setting
// files as a list. Renames and reshapes only: it never changes a value or a label (CLAUDE.md rule 1).
import type { ConfigVersion, LlmSettings, Settings } from "./settings-types";

export interface RealSettings {
  llm: {
    version: string;
    label: LlmSettings["label"];
    default_provider: string;
    providers: Record<string, { model: string }>;
    tasks: Record<string, { provider: string; model: string }>;
    embeddings?: { provider: string; model: string } | null;
  };
  config: ConfigVersion[];
}

export const toSettings = (real: RealSettings): Settings => ({
  llm: {
    version: real.llm.version,
    label: real.llm.label,
    default_provider: real.llm.default_provider,
    providers: Object.entries(real.llm.providers).map(([name, p]) => ({ name, model: p.model })),
    tasks: Object.entries(real.llm.tasks).map(([task, t]) => ({ task, provider: t.provider, model: t.model })),
    embeddings: real.llm.embeddings ?? null,
  },
  config: real.config.map((c) => ({ name: c.name, used_for: c.used_for, version: c.version, label: c.label })),
});
