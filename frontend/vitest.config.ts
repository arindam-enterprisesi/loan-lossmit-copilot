import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // Vitest transforms JSX itself; no React plugin needed. "automatic" matches Next's JSX runtime.
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
    clearMocks: true,
  },
});
