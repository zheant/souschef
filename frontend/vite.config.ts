import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Le proxy /api → api:8000 évite toute configuration CORS en développement.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_URL ?? "http://api:8000", changeOrigin: true } },
  },
});
