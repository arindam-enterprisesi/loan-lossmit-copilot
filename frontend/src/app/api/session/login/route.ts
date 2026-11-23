import type { NextRequest } from "next/server";
import { loginHandler } from "@/lib/auth-handlers";

export const dynamic = "force-dynamic";

export const POST = (request: NextRequest) => loginHandler(request);
