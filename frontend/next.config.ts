import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the tracing root to frontend/ so a stray lockfile higher up (e.g. in a home folder)
  // is never picked as the workspace root.
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
