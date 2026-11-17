// Friendly aliases over the generated contract types (src/lib/api-types.ts).
// Never edit api-types.ts by hand: run `npm run gen:types` after the contract changes.
import type { components } from "./api-types";

type S = components["schemas"];

export type Pillar = S["Pillar"];
export type Case = S["Case"];
export type CaseProfile = S["CaseProfile"];
export type DocumentSummary = S["DocumentSummary"];
export type DocumentType = S["DocumentType"];
export type DocumentStatus = S["DocumentStatus"];
export type Field = S["Field"];
export type Flag = S["Flag"];
export type Severity = S["Severity"];
export type Certainty = S["Certainty"];
export type Evidence = S["Evidence"];
export type BoundingBox = S["BoundingBox"];
export type Job = S["Job"];
export type CompletenessResult = S["CompletenessResult"];
export type CompletenessItem = S["CompletenessItem"];
export type Role = S["Role"];
