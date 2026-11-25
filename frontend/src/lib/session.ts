// Who is signed in, and what they may see. Pure helpers with no framework imports, so the middleware,
// the route handlers, the server pages and the components all use the same rules.
//
// How sign-in works in real mode (NEXT_PUBLIC_USE_MOCKS=false):
//  - The browser never holds the access token. Signing in stores it in an httpOnly cookie
//    (`TOKEN_COOKIE`), which JavaScript cannot read.
//  - A second cookie (`USER_COOKIE`) holds only the name and role, so the screens can say who is
//    signed in. It is not a secret, and it grants nothing: the backend checks the token on every call.
//  - Calls from the browser go to this app's own `/api/proxy/...`, which adds the token and forwards
//    them to the backend. Pages that load data on the server read the token cookie themselves.
import type { Pillar } from "./types";

export const TOKEN_COOKIE = "copilot_token";
export const USER_COOKIE = "copilot_user";

export type Role = "underwriter" | "lm_specialist" | "admin";

export interface SessionUser {
  id: string;
  name: string;
  role: Role;
}

const ROLES: Role[] = ["underwriter", "lm_specialist", "admin"];

export const ROLE_LABEL: Record<Role, string> = {
  underwriter: "Underwriter",
  lm_specialist: "Loss mitigation specialist",
  admin: "Administrator",
};

/** The demo users the backend seeds (README). Only their names are listed: the password is never kept here. */
export const DEMO_USERNAMES: { username: Role; label: string }[] = [
  { username: "underwriter", label: "Underwriter" },
  { username: "lm_specialist", label: "Loss mitigation specialist" },
  { username: "admin", label: "Administrator" },
];

/** Reads the readable user cookie. Anything that is not a well-formed user is treated as signed out. */
export function parseSessionUser(raw: string | null | undefined): SessionUser | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<SessionUser> | null;
    if (
      value &&
      typeof value.id === "string" &&
      typeof value.name === "string" &&
      typeof value.role === "string" &&
      ROLES.includes(value.role as Role)
    ) {
      return { id: value.id, name: value.name, role: value.role as Role };
    }
  } catch {
    // fall through: not JSON
  }
  return null;
}

/** The pillars this role can see. The backend hides the other pillar's cases from it as well. */
export function pillarsFor(role: Role): Pillar[] {
  if (role === "underwriter") return ["underwriting"];
  if (role === "lm_specialist") return ["loss_mitigation"];
  return ["underwriting", "loss_mitigation"];
}

export const canSeePillar = (user: SessionUser, pillar: Pillar): boolean => pillarsFor(user.role).includes(pillar);

/** Where a person lands after signing in: the first pillar they can see. */
export function homePathFor(role: Role): string {
  return pillarsFor(role)[0] === "loss_mitigation" ? "/loss-mitigation" : "/underwriting";
}

/**
 * A `next` address from the query string, only if it stays inside this app: it must start with a
 * single "/". Anything else (another site, a protocol-relative "//host") is dropped, so the sign-in
 * page cannot be used to send someone elsewhere.
 */
export function safeNextPath(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  return next;
}
