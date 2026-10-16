import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import fs from "fs";
import path from "path";
import { helpDevRoutes, helpPrerender } from "./scripts/help_prerender";

// A hosting package's module when this checkout has one; otherwise the planner runs on its own.
const extension = (hosted: string, none: string) =>
  path.resolve(__dirname, fs.existsSync(path.resolve(__dirname, hosted)) ? hosted : none);

export default defineConfig(({ command }) => ({
  plugins: [react(), helpPrerender(), helpDevRoutes()],
  test: {
    environment: "jsdom",
    globals: true,
    reporters: ["default", "junit"],
    outputFile: { junit: "coverage/junit.xml" },
    setupFiles: ["./src/setupTests.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/setupTests.ts",
        "src/test_support/**",
      ],
      reporter: ["text", "html", "json", "json-summary", "lcov"],
      // Ratcheted from the expanded persistence and navigation suite.
      thresholds: { lines: 81.3, statements: 78.9, functions: 76.2, branches: 72 },
    },
  },
  resolve: {
    alias: {
      "@extensions/active": extension("src/business/extensions.tsx", "src/extensions/none.ts"),
      "@extensions/help": extension(
        "src/business/help/help_extensions.tsx",
        "src/extensions/no_help.ts",
      ),
      "@extensions/startup": extension("src/business/startup.ts", "src/extensions/no_startup.ts"),
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, "index.html"),
        help: path.resolve(__dirname, "help.html"),
      },
    },
  },
  server: {
    proxy:
      command === "serve"
        ? {
            "/api": {
              target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
              changeOrigin: true,
            },
          }
        : undefined,
  },
}));
