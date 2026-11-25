import { NextResponse, type NextRequest } from "next/server";
import { mocksOn } from "@/lib/backend-url";
import { safeNextPath, TOKEN_COOKIE } from "@/lib/session";

/**
 * In real mode every page except the sign-in page needs a token cookie. Without one, a page sends
 * the person to /login (remembering where they were going) and an API call answers 401. With the
 * demo data on there is no sign-in at all.
 */
export function middleware(request: NextRequest) {
  if (mocksOn()) return NextResponse.next();

  const { pathname, search } = request.nextUrl;
  if (pathname === "/login" || pathname.startsWith("/api/session/")) return NextResponse.next();
  if (request.cookies.get(TOKEN_COOKIE)?.value) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ code: "unauthorized", message: "Sign in to continue." }, { status: 401 });
  }
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  const back = safeNextPath(`${pathname}${search}`);
  if (back && back !== "/") url.searchParams.set("next", back);
  return NextResponse.redirect(url);
}

export const config = {
  // Not the framework's own files, the icon, or the mock page pictures.
  matcher: ["/((?!_next/|favicon.ico|mock/).*)"],
};
