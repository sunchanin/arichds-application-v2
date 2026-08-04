import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * In production the SPA is served by FastAPI from the same origin, so there is
 * no CORS story at all (SPEC §3.1). In development Vite proxies `/api` to the
 * backend, which keeps the frontend code identical in both settings — it always
 * calls a same-origin relative URL.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    // `arichds.fe_static.resolve_fe_dist()` looks for <repo>/web/dist.
    outDir: "dist",
    sourcemap: false,
  },
});
