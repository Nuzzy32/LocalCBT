import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [react()],
	// Dev: same-origin /api ke FastAPI lokal. Produksi: Caddy (infrastructure/proxy).
	server: { proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } } },
});
