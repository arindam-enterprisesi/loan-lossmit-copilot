import type { NextRequest } from "next/server";
import { forwardToBackend } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

const handler = async (request: NextRequest, { params }: Context) => forwardToBackend(request, (await params).path);

export { handler as GET, handler as POST, handler as PUT, handler as PATCH, handler as DELETE };
