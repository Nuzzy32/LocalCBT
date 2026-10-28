import { defineConfig, devices } from "@playwright/test";
import { ADMIN } from "./e2e/helpers";

// M9-01: regresi E2E (desktop) lalu alur siswa di ponsel (WebKit/iPhone & Chromium/Android).
// Butuh PostgreSQL dev (compose.dev.yml) dan uv; jalankan: pnpm e2e
export default defineConfig({
	testDir: "e2e",
	outputDir: "e2e/.tmp/results",
	timeout: 60_000,
	expect: { timeout: 10_000 },
	retries: 0,
	reporter: process.env.CI
		? [["list"], ["html", { open: "never", outputFolder: "e2e/.tmp/report" }]]
		: "list",
	use: {
		baseURL: "http://localhost:5174",
		locale: "id-ID",
		timezoneId: "Asia/Jakarta",
		// Transisi warna membuat axe mengukur kontras di tengah animasi.
		reducedMotion: "reduce",
		trace: "retain-on-failure",
	},
	projects: [
		{
			name: "desktop",
			testMatch: "regression.spec.ts",
			use: devices["Desktop Chrome"],
		},
		{
			name: "iphone",
			testMatch: "mobile.spec.ts",
			dependencies: ["desktop"],
			use: devices["iPhone 13"],
		},
		// DESIGN_SYSTEM: "pengujian kritis pada 360px" (ponsel Android kelas bawah).
		{
			name: "android",
			testMatch: "mobile.spec.ts",
			dependencies: ["desktop"],
			use: { ...devices["Pixel 7"], viewport: { width: 360, height: 780 } },
		},
		{
			name: "desktop-lanjutan",
			testMatch: ["keyboard.spec.ts", "offline.spec.ts"],
			dependencies: ["desktop"],
			use: devices["Desktop Chrome"],
		},
	],
	webServer: [
		{
			command: "sh e2e/api.sh",
			url: "http://127.0.0.1:8200/api/v1/healthz",
			env: { E2E_ADMIN_PASSWORD: ADMIN.password },
			timeout: 120_000,
			stdout: "pipe",
		},
		{
			command: "pnpm exec vite --port 5174 --strictPort",
			url: "http://localhost:5174",
			env: { LOCALCBT_API_URL: "http://127.0.0.1:8200" },
		},
	],
});
