// Loading data on the Next server, for pages that render before the browser is involved. The browser's
// token lives in an httpOnly cookie, so these read it from the request and send it to the backend.
//
// With the demo data on they simply return the mock data, as before. Only for use in server
// components: it imports next/headers.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { listCases, listDocuments } from "./api";
import { ApiError } from "./api-error";
import { backendUrl, mocksOn } from "./backend-url";
import { TOKEN_COOKIE } from "./session";
import type { Case, DocumentSummary, Pillar } from "./types";

async function serverGet<T>(path: string): Promise<T> {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) redirect("/login");

  let res: Response;
  try {
    res = await fetch(`${backendUrl()}${path}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  } catch {
    throw new ApiError(502, "The server could not be reached. Is the backend running?");
  }
  // The token was refused: ask for sign-in again.
  if (res.status === 401) redirect("/login?expired=1");
  if (!res.ok) {
    let message = `The server answered ${res.status} for ${path}.`;
    try {
      const body = (await res.json()) as { message?: string };
      if (body.message) message = body.message;
    } catch {
      // keep the default message
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

/** The cases this person can see in one pillar. */
export async function loadCases(pillar: Pillar): Promise<Case[]> {
  if (mocksOn()) return listCases(pillar);
  return (await serverGet<{ items: Case[] }>(`/cases?pillar=${pillar}`)).items;
}

/** The documents of one case. */
export async function loadDocuments(caseId: string): Promise<DocumentSummary[]> {
  if (mocksOn()) return listDocuments(caseId);
  return (await serverGet<{ items: DocumentSummary[] }>(`/cases/${caseId}/documents`)).items;
}
