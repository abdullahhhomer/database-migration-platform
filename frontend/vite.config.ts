import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker, nginx proxies /api to the backend. For `npm run dev` the Vite
// server does the same against the backend published on localhost:8000.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/health": backend,
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/api": backend,
      "/health": backend,
    },
  },
});
