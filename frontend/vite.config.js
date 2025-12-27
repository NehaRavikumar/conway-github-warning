import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/stream": "http://127.0.0.1:8000",
      "/summary": "http://127.0.0.1:8000",
      "/dev": "http://127.0.0.1:8000",
      "/debug": "http://127.0.0.1:8000"
    }
  }
});
