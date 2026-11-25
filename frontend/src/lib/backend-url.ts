/**
 * Where the FastAPI backend is, for code that runs on the Next server (route handlers and server
 * pages). `API_URL` is only for the server; `NEXT_PUBLIC_API_URL` is the older setting and still
 * works. The browser never calls this address: it calls this app's `/api/proxy`.
 */
export function backendUrl(): string {
  const url = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
  return url.replace(/\/+$/, "");
}

/** True when the screens run on built-in mock data, with no sign-in and no backend. */
export const mocksOn = (): boolean => process.env.NEXT_PUBLIC_USE_MOCKS !== "false";
