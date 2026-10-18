import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const SERVICE_ADDRESS = "http://127.0.0.1:8770";    // the default port of `usc ui`

export default defineConfig({
  plugins: [react()],
  server: {
    // changeOrigin makes the Host header the service's own address, which the service requires.
    proxy: { "/api": { target: SERVICE_ADDRESS, changeOrigin: true, ws: true } },
  },
  test: { environment: "jsdom" },
});
