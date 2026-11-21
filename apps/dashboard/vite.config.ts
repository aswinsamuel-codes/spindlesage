import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev: the dashboard runs on :5173 and proxies /api to the FastAPI server on :8000.
// Build: the output is served by FastAPI at /dashboard/, on the same origin as the API.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/dashboard/" : "/",
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
}));
