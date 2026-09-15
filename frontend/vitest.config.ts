import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    // Playwright owns e2e/. Without this vitest collects those specs,
    // imports @playwright/test, and fails on a `test` that is not its own.
    exclude: ["node_modules/**", "dist/**", "e2e/**"],
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
