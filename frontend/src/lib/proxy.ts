import { NextResponse, type NextRequest } from "next/server";
import { clearSessionCookies } from "./auth-handlers";
import { backendUrl, mocksOn } from "./backend-url";
import { TOKEN_COOKIE } from "./session";

const reply = (status: number, message: string, code: string) => NextResponse.json({ code, message }, { status });

/** A path piece is ordinary text: letters, digits and a few marks. No slashes, no "." or "..". */
const SEGMENT = /^[A-Za-z0-9._~@:-]+$/;
export const isSafePath = (segments: string[]): boolean =>
  segments.length > 0 && segments.every((s) => s !== "." && s !== ".." && SEGMENT.test(s));

const SAFE_METHODS = new Set(["GET", "HEAD"]);
const NO_BODY_STATUS = new Set([204, 205, 304]);

/**
 * Passes one call from the browser on to the backend, adding the access token from the httpOnly
 * cookie. So the browser only ever talks to this app (no cross-site calls, no token in scripts).
 *
 * It only forwards to the configured backend address, and only for paths made of plain pieces.
 * A call that changes something must come from this app's own address, which stops another site
 * from using someone's cookie. A 401 from the backend signs the person out.
 */
export async function forwardToBackend(request: NextRequest, segments: string[]): Promise<Response> {
  if (mocksOn()) return reply(404, "The proxy is off while the demo data is on.", "not_found");
  if (!isSafePath(segments)) return reply(400, "That address is not allowed.", "bad_request");

  const token = request.cookies.get(TOKEN_COOKIE)?.value;
  if (!token) return reply(401, "Sign in to continue.", "unauthorized");

  const origin = request.headers.get("origin");
  if (!SAFE_METHODS.has(request.method) && origin && new URL(origin).host !== request.nextUrl.host) {
    return reply(403, "That call did not come from this app.", "forbidden");
  }

  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  for (const name of ["content-type", "accept"]) {
    const value = request.headers.get(name);
    if (value) headers[name] = value;
  }

  let body: ArrayBuffer | undefined;
  if (!SAFE_METHODS.has(request.method)) {
    const bytes = await request.arrayBuffer();
    if (bytes.byteLength > 0) body = bytes;
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backendUrl()}/${segments.join("/")}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return reply(502, "The server could not be reached. Is the backend running?", "unreachable");
  }

  const out = new NextResponse(NO_BODY_STATUS.has(upstream.status) ? null : await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: upstream.headers.get("content-type") ? { "content-type": upstream.headers.get("content-type")! } : undefined,
  });
  // The token was refused (expired or revoked): forget it, so the next page asks for sign-in.
  return upstream.status === 401 ? clearSessionCookies(out, request.nextUrl.protocol === "https:") : out;
}
