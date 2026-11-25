// Stand-in for the backend's settings while NEXT_PUBLIC_USE_MOCKS=true. The values are the ones in the backend's
// own files on 24 Nov 2026 (backend/config/llm.yaml, and the version and label at the top of each file there), so
// the screen reads the way the real answer will. It is replaced by the real API.
import type { Settings } from "@/lib/settings-types";

const CLAUDE = "claude-opus-5-5";

export const mockSettings: Settings = {
  llm: {
    version: "2026-11-19.1",
    label: "illustrative",
    default_provider: "anthropic",
    providers: [
      { name: "anthropic", model: CLAUDE },
      { name: "bedrock", model: "anthropic.claude-opus-5-5" },
      { name: "gemini", model: "gemini-flash-latest" },
      { name: "openai", model: "gpt-5.6-terra" },
    ],
    tasks: [
      { task: "smoke", provider: "anthropic", model: CLAUDE },
      { task: "classify", provider: "anthropic", model: CLAUDE },
      { task: "extract", provider: "anthropic", model: CLAUDE },
      { task: "label_transactions", provider: "anthropic", model: CLAUDE },
      { task: "hardship", provider: "anthropic", model: CLAUDE },
      { task: "income_explain", provider: "anthropic", model: CLAUDE },
    ],
    embeddings: { provider: "openai", model: "text-embedding-3-small" },
  },
  config: [
    { name: "llm.yaml", used_for: "Which provider and model does each task", version: "2026-11-19.1", label: "illustrative" },
    { name: "thresholds.yaml", used_for: "Review levels for income, assets, hardship and the budget", version: "2026-11-24.1", label: "illustrative" },
    { name: "income_method.yaml", used_for: "How income is worked out, and the income flag messages", version: "2026-11-19.1", label: "illustrative" },
    { name: "checklists.yaml", used_for: "The required documents for each case type", version: "2026-11-19.1", label: "illustrative" },
    { name: "document_fields.yaml", used_for: "The values read from each document type", version: "2026-11-23.1", label: "illustrative" },
    { name: "validation.yaml", used_for: "The checks run on a document, and their messages", version: "2026-11-18.1", label: "illustrative" },
    { name: "hardship.yaml", used_for: "How the hardship letter is read", version: "2026-11-19.1", label: "illustrative" },
    { name: "ingestion.yaml", used_for: "Limits on uploaded files", version: "2026-11-23.1", label: "illustrative" },
    { name: "auth.yaml", used_for: "The demo sign-in", version: "2026-11-17.1", label: "illustrative" },
    { name: "Sample Investor A rule set", used_for: "The loss mitigation waterfall and the lender view settings", version: "1", label: "illustrative" },
  ],
};
