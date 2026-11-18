// Thin API layer. Screens call these functions and never fetch directly, so the swap from mocks
// to the real FastAPI backend (contracts/openapi.yaml) is a flag, not a rewrite.
import { mockCases, mockDocuments } from "@/mocks/data";
import type { Case, DocumentSummary, Pillar } from "./types";

export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API ${res.status} on ${path}`);
  }
  return (await res.json()) as T;
}

export async function listCases(pillar?: Pillar): Promise<Case[]> {
  if (USE_MOCKS) {
    return mockCases.filter((c) => !pillar || c.pillar === pillar);
  }
  const qs = pillar ? `?pillar=${pillar}` : "";
  const data = await request<{ items: Case[] }>(`/cases${qs}`);
  return data.items;
}

export async function listDocuments(caseId: string): Promise<DocumentSummary[]> {
  if (USE_MOCKS) {
    return mockDocuments.filter((d) => d.case_id === caseId);
  }
  const data = await request<{ items: DocumentSummary[] }>(`/cases/${caseId}/documents`);
  return data.items;
}
