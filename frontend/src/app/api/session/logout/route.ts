import type { NextRequest } from "next/server";
import { logoutHandler } from "@/lib/auth-handlers";

export const dynamic = "force-dynamic";

export const POST = (request: NextRequest) => logoutHandler(request);
