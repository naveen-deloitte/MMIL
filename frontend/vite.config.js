import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig(function (_a) {
    var _b;
    var mode = _a.mode;
    var env = loadEnv(mode, ".", "IDP_");
    return {
        plugins: [react()],
        server: {
            port: 5173,
            proxy: {
                "/api": (_b = env.IDP_API_PROXY_TARGET) !== null && _b !== void 0 ? _b : "http://127.0.0.1:8001",
            },
        },
        test: {
            environment: "jsdom",
            setupFiles: "./src/test/setup.ts",
            css: true,
        },
    };
});
