import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "IDP_");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": env.IDP_API_PROXY_TARGET ?? "http://127.0.0.1:8001",
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      css: true,
    },
  };
});
