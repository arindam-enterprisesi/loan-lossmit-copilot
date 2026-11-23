// Turns what the real backend sends for the Underwriting copilot and the Loss Mitigation recommendation
// (backend/app/api/schemas/reports.py, on `main`) into the shapes the screens use (copilot-types.ts). It
// renames and reshapes; it calculates nothing (CLAUDE.md rule 1). Not tried against a running backend.
//
// What differs from the screens' shapes:
// - statuses: the backend's "queued" is "waiting" here and "succeeded" is "done" for an agent;
// - every attempt of an agent is a row, so the latest attempt of each is the one shown;
// - the snapshot is an object, and an evidence reference is an object with a `type`;
// - a loss mitigation answer carries its agent runs and sign-offs inside `report`;
// - people are user IDs (the backend sends no names yet).
import type {
  AgentName,
  AgentRun,
  AgentStatus,
  Condition,
  ConditionAddRequest,
  ConditionDecisionRequest,
  Conflict,
  EvidenceRef,
  Finding,
  GuidelineReference,
  LenderFigure,
  LenderView,
  LmRecommendation,
  LmSections,
  OverrideRequest,
  OverrideStatus,
  Priority,
  ReportInfo,
  ReportStatus,
  RunStatus,
  SignOff,
  SignOffResult,
  SnapshotItem,
  UnderwritingReport,
  UnderwritingSections,
  WaterfallCondition,
  WaterfallOption,
} from "./copilot-types";

// ---- What the backend sends (only the fields read here) ---------------------------------------------

type Json = Record<string, unknown>;

export interface RealAgentRun {
  agent: AgentName;
  attempt: number;
  status: "queued" | "running" | "succeeded" | "failed";
  output: Json | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RealFinding {
  id: string;
  priority: Priority;
  title: string;
  detail: string;
  evidence: Json[];
}

export type RealCondition = Condition;

export interface RealSignOff {
  id: string;
  report_version: number;
  signed_by: string;
  role: string;
  signed_at: string;
  note: string | null;
  statement: string;
}

export interface RealReportBundle {
  run_id: string;
  run_status: "queued" | "running" | "succeeded" | "failed";
  report: {
    id: string;
    version: number;
    status: ReportStatus;
    source: "agents" | "seeded_sample";
    notice: string | null;
    created_at: string;
    sections: Json;
    guardrail_results: Json;
  };
  findings: RealFinding[];
  conditions: RealCondition[];
  agent_runs: RealAgentRun[];
  sign_offs: RealSignOff[];
}

export interface RealWaterfallCondition {
  id: string;
  label: string;
  expression: string;
  values: Json;
  passage_id: string | null;
  derived: boolean;
  status: WaterfallCondition["status"];
  effective_status: WaterfallCondition["effective_status"];
  override: { status: OverrideStatus; reason: string; by: string; at: string } | null;
}

export interface RealWaterfallOption {
  option: WaterfallOption["option"];
  order_no: number;
  status: WaterfallOption["status"];
  original_status: WaterfallOption["original_status"];
  conditions: RealWaterfallCondition[];
  overridden: boolean;
}

export interface RealLenderView {
  foreclosure_loss: string;
  modification_cost: string;
  advantage: string;
  settings: Record<string, string | number>;
  figures: { name: string; value: string; unit: string; formula: string; working: string }[];
  final_terms: string;
}

export interface RealLmRecommendation {
  run_id: string;
  run_status: "queued" | "running" | "succeeded" | "failed";
  source: "rules_engine" | "seeded_sample";
  notice: string | null;
  rule_set: LmRecommendation["rule_set"];
  waterfall: RealWaterfallOption[];
  lender_view: RealLenderView | null;
  report: RealReportBundle | null;
}

export interface RealSignOffResult {
  sign_off: RealSignOff;
  report_status: ReportStatus;
  pending_conditions: number;
}

// ---- The pieces -------------------------------------------------------------------------------------

const AGENT_STATUS: Record<RealAgentRun["status"], AgentStatus> = {
  queued: "waiting",
  running: "running",
  succeeded: "done",
  failed: "failed",
};

const RUN_STATUS: Record<RealReportBundle["run_status"], RunStatus> = {
  queued: "running",
  running: "running",
  succeeded: "succeeded",
  failed: "failed",
};

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const textList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** The latest attempt of each agent, with the status in the screens' words and the agent's own one-line summary. */
export function toAgentRuns(runs: RealAgentRun[]): AgentRun[] {
  const latest = new Map<AgentName, RealAgentRun>();
  for (const r of runs) {
    const seen = latest.get(r.agent);
    if (!seen || r.attempt > seen.attempt) latest.set(r.agent, r);
  }
  return [...latest.values()].map((r) => ({
    agent: r.agent,
    attempt: r.attempt,
    status: AGENT_STATUS[r.status] ?? "waiting",
    summary: text(r.output?.summary),
    error: r.error,
    started_at: r.started_at,
    finished_at: r.finished_at,
  }));
}

/** {"type": "calculation", "name": "dti"} becomes a reference to "dti". A reference that names nothing is left out. */
export function toEvidenceRef(raw: Json): EvidenceRef | null {
  const type = raw.type;
  if (type === "calculation") return text(raw.name) ? { kind: "calculation", id: raw.name as string } : null;
  if (type === "rule" || type === "checklist") return text(raw.id) ? { kind: type, id: raw.id as string } : null;
  if (type === "document") {
    const id = text(raw.document_id) ?? text(raw.id);
    if (!id) return null;
    const lines = textList(raw.line_ids);
    return lines.length ? { kind: "document", id, line_ids: lines } : { kind: "document", id };
  }
  if (type === "passage") {
    const id = text(raw.passage_id) ?? text(raw.id);
    return id ? { kind: "passage", id } : null;
  }
  return null;
}

const evidenceList = (raw: unknown): EvidenceRef[] =>
  Array.isArray(raw) ? raw.flatMap((r) => (r && typeof r === "object" ? [toEvidenceRef(r as Json)] : [])).filter((r): r is EvidenceRef => r !== null) : [];

const toFinding = (f: RealFinding): Finding => ({ id: f.id, priority: f.priority, title: f.title, detail: f.detail, evidence: evidenceList(f.evidence) });

const toSignOff = (s: RealSignOff): SignOff => ({
  id: s.id,
  report_version: s.report_version,
  signed_by: s.signed_by,
  role: s.role,
  signed_at: s.signed_at,
  note: s.note,
  statement: s.statement,
});

/** The backend's reply to a sign-off. */
export const toSignOffResult = (r: RealSignOffResult): SignOffResult => ({
  sign_off: toSignOff(r.sign_off),
  report_status: r.report_status,
  pending_conditions: r.pending_conditions,
});

function toReference(raw: unknown): GuidelineReference | null {
  if (typeof raw === "string") return { passage_id: raw, summary: "" };
  if (raw && typeof raw === "object") {
    const o = raw as Json;
    const id = text(o.passage_id) ?? text(o.id);
    return id ? { passage_id: id, summary: text(o.summary) ?? text(o.text) ?? "" } : null;
  }
  return null;
}

const toSnapshot = (raw: unknown): SnapshotItem[] =>
  raw && typeof raw === "object" ? Object.entries(raw as Json).map(([key, value]) => ({ key, value: String(value ?? "") })) : [];

function toConflicts(raw: unknown): Conflict[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((c) => {
    if (!c || typeof c !== "object") return [];
    const o = c as Json;
    return [{ title: text(o.title) ?? "", detail: text(o.detail) ?? "", evidence: evidenceList(o.evidence) }];
  });
}

export function toUnderwritingSections(s: Json): UnderwritingSections {
  return {
    snapshot: toSnapshot(s.snapshot),
    conflicts: toConflicts(s.conflicts),
    missing_information: textList(s.missing_information),
    potential_risks: textList(s.potential_risks),
    guideline_references: (Array.isArray(s.guideline_references) ? s.guideline_references : []).flatMap((r) => {
      const ref = toReference(r);
      return ref ? [ref] : [];
    }),
    note: text(s.note),
  };
}

export function toLmSections(s: Json): LmSections {
  return {
    lender_view: text(s.lender_view) ?? "",
    borrower_situation: text(s.borrower_situation) ?? "",
    missing_information: textList(s.missing_information),
    compliance_points: textList(s.compliance_points),
    items_for_human_review: textList(s.items_for_human_review),
    note: text(s.note),
  };
}

/** A failed Critic means the report was not checked. A report with no Critic row at all (a seeded sample) is not marked. */
const criticMissing = (runs: AgentRun[]): boolean => runs.some((r) => r.agent === "critic" && r.status === "failed");

function toInfo<S>(real: RealReportBundle["report"], sections: S, runs: AgentRun[]): ReportInfo<S> {
  return {
    id: real.id,
    version: real.version,
    status: real.status,
    source: real.source,
    notice: real.notice,
    created_at: real.created_at,
    sections,
    critic_missing: criticMissing(runs),
  };
}

// ---- Underwriting -----------------------------------------------------------------------------------

export function toUnderwritingReport(real: RealReportBundle): UnderwritingReport {
  const agent_runs = toAgentRuns(real.agent_runs);
  return {
    run_id: real.run_id,
    run_status: RUN_STATUS[real.run_status] ?? "running",
    report: toInfo(real.report, toUnderwritingSections(real.report.sections), agent_runs),
    findings: real.findings.map(toFinding),
    conditions: real.conditions.map((c) => ({ ...c })),
    agent_runs,
    sign_offs: real.sign_offs.map(toSignOff),
  };
}

/** The body of a condition decision: only the fields the backend takes, and none that are empty. */
export function decisionBody(req: ConditionDecisionRequest): ConditionDecisionRequest {
  const body: ConditionDecisionRequest = { decision: req.decision };
  if (req.edited_text !== undefined) body.edited_text = req.edited_text.trim();
  if (req.reason !== undefined) body.reason = req.reason.trim();
  return body;
}

export const addBody = (req: ConditionAddRequest): ConditionAddRequest => ({ text: req.text.trim(), priority: req.priority });

// ---- Loss mitigation --------------------------------------------------------------------------------

const toValues = (raw: Json): Record<string, string> => Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, String(v ?? "")]));

const toWaterfallCondition = (c: RealWaterfallCondition): WaterfallCondition => ({
  id: c.id,
  label: c.label,
  expression: c.expression,
  values: toValues(c.values ?? {}),
  passage_id: c.passage_id,
  derived: c.derived,
  status: c.status,
  effective_status: c.effective_status,
  override: c.override ? { status: c.override.status, reason: c.override.reason, by: c.override.by, at: c.override.at } : null,
});

const toLenderView = (v: RealLenderView): LenderView => ({
  foreclosure_loss: v.foreclosure_loss,
  modification_cost: v.modification_cost,
  advantage: v.advantage,
  settings: v.settings,
  figures: v.figures.map((f): LenderFigure => ({ name: f.name, value: f.value, unit: f.unit, formula: f.formula, working: f.working })),
  final_terms: v.final_terms,
});

export function toLmRecommendation(real: RealLmRecommendation): LmRecommendation {
  const agent_runs = real.report ? toAgentRuns(real.report.agent_runs) : [];
  return {
    run_id: real.run_id,
    run_status: RUN_STATUS[real.run_status] ?? "running",
    source: real.source,
    notice: real.notice,
    rule_set: real.rule_set,
    waterfall: real.waterfall.map((o) => ({
      option: o.option,
      order_no: o.order_no,
      status: o.status,
      original_status: o.original_status,
      conditions: o.conditions.map(toWaterfallCondition),
      overridden: o.overridden,
    })),
    lender_view: real.lender_view ? toLenderView(real.lender_view) : null,
    report: real.report ? toInfo(real.report.report, toLmSections(real.report.report.sections), agent_runs) : null,
    agent_runs,
    sign_offs: real.report ? real.report.sign_offs.map(toSignOff) : [],
  };
}

/** The body of an override: a status and a trimmed reason. */
export const overrideBody = (req: OverrideRequest): OverrideRequest => ({ status: req.status, reason: req.reason.trim() });
