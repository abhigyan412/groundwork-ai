import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    // Same origin in dev as behind nginx: no CORS needed (docs/architecture.md).
    proxy: {
      "/api": backend,
      "/auth": backend,
      "/health": backend,
    },
  },
  build: { sourcemap: true },
});
