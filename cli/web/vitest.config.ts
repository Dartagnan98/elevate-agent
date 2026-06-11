import path from "node:path";
import { defineConfig } from "vitest/config";

// Separate from vite.config.ts: the app config pulls in the React/Tailwind
// plugin chain + dev-token middleware, none of which the pure-module store
// tests need (and the plugins slow cold starts). Same "@" alias.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/__tests__/**/*.test.ts"],
  },
});
