import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/process": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      "/federation": "http://localhost:8000",
      "/biometric": "http://localhost:8000",
    },
  },
});