import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

declare const process: { env: Record<string, string | undefined> };
const api = process.env.LOCALCBT_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
	plugins: [react()],
	// Dev: same-origin /api ke FastAPI lokal (E2E: server terpisah). Produksi: Caddy (infrastructure/proxy).
	server: { proxy: { "/api": { target: api, ws: true } } },
});
