import { NextResponse, type NextRequest } from "next/server";
import { backendUrl, mocksOn } from "./backend-url";
import { TOKEN_COOKIE, USER_COOKIE, parseSessionUser, type SessionUser } from "./session";

const reply = (status: number, message: string, code?: string) =>
  NextResponse.json({ code: code ?? "error", message }, { status });

const cookieBase = (secure: boolean) => ({ sameSite: "lax" as const, secure, path: "/" });

/** Cookies are removed by setting them empty and already expired. */
export function clearSessionCookies(response: NextResponse, secure = false): NextResponse {
  response.cookies.set(TOKEN_COOKIE, "", { ...cookieBase(secure), httpOnly: true, maxAge: 0 });
  response.cookies.set(USER_COOKIE, "", { ...cookieBase(secure), httpOnly: false, maxAge: 0 });
  return response;
}

/**
 * POST /api/session/login with `{ username, password }`. Signs in against the backend, then keeps the
 * access token in an httpOnly cookie, so the browser's own scripts never see it. Only the name and
 * role go into a readable cookie. The password is passed straight on and never stored or logged.
 */
export async function loginHandler(request: NextRequest): Promise<Response> {
  if (mocksOn()) return reply(404, "Sign-in is off while the demo data is on.", "not_found");

  let body: { username?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return reply(400, "Enter a username and a password.", "bad_request");
  }
  const { username, password } = body ?? {};
  if (
    typeof username !== "string" ||
    typeof password !== "string" ||
    !username.trim() ||
    !password ||
    username.length > 64 ||
    password.length > 256
  ) {
    return reply(400, "Enter a username and a password.", "bad_request");
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backendUrl()}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username.trim(), password }),
      cache: "no-store",
    });
  } catch {
    return reply(502, "The server could not be reached. Is the backend running?", "unreachable");
  }

  if (upstream.status === 401 || upstream.status === 422) {
    return reply(401, "Incorrect username or password.", "invalid_credentials");
  }
  if (!upstream.ok) return reply(502, `Sign-in did not work (the server answered ${upstream.status}).`, "upstream_error");

  let data: { access_token?: unknown; expires_in?: unknown; user?: unknown };
  try {
    data = await upstream.json();
  } catch {
    return reply(502, "The server's sign-in answer could not be read.", "upstream_error");
  }
  const user = parseSessionUser(JSON.stringify(data.user));
  if (typeof data.access_token !== "string" || !data.access_token || !user) {
    return reply(502, "The server's sign-in answer was not what was expected.", "upstream_error");
  }

  const secure = request.nextUrl.protocol === "https:";
  // The cookies end when the token does, so an old session sends the person to sign in again.
  const maxAge = typeof data.expires_in === "number" && data.expires_in > 0 ? Math.floor(data.expires_in) : 3600;
  const response = NextResponse.json({ user } satisfies { user: SessionUser });
  response.cookies.set(TOKEN_COOKIE, data.access_token, { ...cookieBase(secure), httpOnly: true, maxAge });
  response.cookies.set(USER_COOKIE, JSON.stringify(user), { ...cookieBase(secure), httpOnly: false, maxAge });
  return response;
}

/** POST /api/session/logout: forgets the token. The backend keeps no session, so there is nothing to tell it. */
export async function logoutHandler(request: NextRequest): Promise<Response> {
  return clearSessionCookies(NextResponse.json({ ok: true }), request.nextUrl.protocol === "https:");
}
