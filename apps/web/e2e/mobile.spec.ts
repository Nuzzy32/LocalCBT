import { expect, test } from "@playwright/test";
import {
	answerAll,
	checkA11y,
	EXAM,
	expectNoHorizontalScroll,
	expectTouchTargets,
	loadState,
	login,
	TOKEN,
} from "./helpers";

// Siswa mengerjakan ujian dari ponsel (data dari regression.spec.ts, proyek "desktop").
test("siswa (ponsel): login, token, navigasi nomor soal, kumpulkan", async ({
	page,
}, info) => {
	const student = loadState()[info.project.name];
	const screen = async (name: string) => {
		await checkA11y(page, `${info.project.name}-${name}`);
		await expectNoHorizontalScroll(page, name);
		await expectTouchTargets(page, name);
		await page.screenshot({
			path: `e2e/.tmp/screens/${info.project.name}-${name}.png`,
		});
	};

	await page.goto("/");
	await screen("login");
	await login(page, student);
	await expect(page.getByText(EXAM)).toBeVisible();
	await screen("daftar");

	await page.getByRole("button", { name: "Mulai" }).click();
	await page.getByLabel("Token ujian dari pengawas").fill(TOKEN);
	await page.getByRole("button", { name: "Lanjut" }).click();
	await page.getByLabel("Saya sudah membaca petunjuk").check();
	await screen("petunjuk");
	await page.getByRole("button", { name: "Mulai ujian" }).click();

	await expect(page.getByRole("button", { name: "Nomor soal" })).toBeVisible();
	await expect(
		page.getByRole("button", { name: "Kumpulkan ujian" }),
	).toBeHidden();
	await screen("soal");
	// UX-02: pindah nomor lewat lembar nomor soal tanpa kehilangan jawaban.
	await answerAll(page, true);
	await page.getByRole("button", { name: "Nomor soal" }).click();
	await expect(
		page.getByRole("dialog").getByText("Terjawab 3 / 3"),
	).toBeVisible();
	await screen("lembar-nomor");
	await page.getByRole("button", { name: "Tutup" }).click();

	// PRD: perubahan orientasi; WCAG 1.4.10 reflow pada lebar 320px.
	const portrait = page.viewportSize() ?? { width: 360, height: 780 };
	for (const size of [
		{ width: portrait.height, height: portrait.width },
		{ width: 320, height: 640 },
	]) {
		await page.setViewportSize(size);
		await expectNoHorizontalScroll(page, `soal ${size.width}×${size.height}`);
		// Lanskap lebar memakai tata letak desktop: tombolnya "Kumpulkan ujian".
		await expect(
			page
				.getByRole("button", { name: /^Kumpulkan/ })
				.filter({ visible: true }),
		).toBeVisible();
	}
	await page.setViewportSize(portrait);

	await page.getByRole("button", { name: "Kumpulkan", exact: true }).click();
	await screen("dialog-kumpulkan");
	await page.getByRole("button", { name: "Ya, kumpulkan" }).click();
	await expect(
		page.getByRole("heading", { name: "Ujian berhasil dikumpulkan." }),
	).toBeVisible();
	await expect(page.getByText(/Nilai: 3(,0+)? dari 3/)).toBeVisible();
	await screen("bukti");
});
