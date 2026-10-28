import { expect, test } from "@playwright/test";
import { EXAM, loadState, login, TOKEN } from "./helpers";

// Sisi UI M9-04: antrean jawaban di perangkat (IndexedDB) saat jaringan putus, lalu tersinkron.
test("siswa: jawaban saat offline diantre di perangkat lalu tersinkron", async ({
	page,
	context,
}) => {
	test.setTimeout(90_000);
	await login(page, loadState().offline);
	await expect(page.getByText(EXAM)).toBeVisible();
	await page.getByRole("button", { name: "Mulai" }).click();
	await page.getByLabel("Token ujian dari pengawas").fill(TOKEN);
	await page.getByRole("button", { name: "Lanjut" }).click();
	await page.getByLabel("Saya sudah membaca petunjuk").check();
	await page.getByRole("button", { name: "Mulai ujian" }).click();

	const status = page
		.getByRole("status")
		.filter({ hasText: /jawaban|Tersimpan|Menyimpan/ });
	const question = page.locator("article.question");
	const firstChoice = question.locator("input").first();
	const answered = (n: number) => page.getByText(`Terjawab ${n} / 3`).first();

	// 1) Perangkat offline: jawaban tetap diterima, ditandai belum tersinkron, submit dikunci.
	await expect(firstChoice).toBeVisible(); // soal termuat saat masih online
	await context.setOffline(true);
	await firstChoice.check();
	await expect(status).toHaveText(
		/1 jawaban tersimpan di perangkat, belum tersinkron/,
	);
	await expect(page.getByText("Koneksi ke server terputus.")).toBeVisible({
		timeout: 20_000,
	});
	const queued = await page.evaluate(
		() =>
			new Promise<number>((resolve) => {
				const req = indexedDB.open("localcbt-offline", 1);
				req.onsuccess = () => {
					const all = req.result
						.transaction("answers")
						.objectStore("answers")
						.getAll();
					all.onsuccess = () => resolve(all.result.length);
				};
			}),
	);
	expect(queued, "jawaban tersimpan di IndexedDB").toBe(1);
	await page.getByRole("button", { name: "Kumpulkan ujian" }).click();
	const dialog = page.getByRole("dialog", { name: "Kumpulkan ujian?" });
	await expect(
		dialog.getByText("Masih ada jawaban yang belum tersimpan di server."),
	).toBeVisible();
	await expect(
		dialog.getByRole("button", { name: "Ya, kumpulkan" }),
	).toBeDisabled();
	await dialog.getByRole("button", { name: "Kembali" }).click();

	// Kembali online: antrean terkirim otomatis, peringatan hilang.
	await context.setOffline(false);
	await expect(status).toHaveText(/Tersimpan di server/, { timeout: 20_000 });
	await expect(page.getByText("Koneksi ke server terputus.")).toBeHidden({
		timeout: 20_000,
	});

	// 2) API tidak terjangkau lalu halaman dimuat ulang (mis. tab crash): antrean dari IndexedDB
	// dikirim ulang saat halaman dibuka kembali.
	await page.getByRole("button", { name: "Berikutnya →" }).click();
	await page.route("**/api/v1/student/attempts/*/answers/*", (r) => r.abort());
	await question.locator("input").first().check();
	await expect(status).toHaveText(/1 jawaban tersimpan di perangkat/);
	await page.unrouteAll({ behavior: "ignoreErrors" });
	await page.reload();
	await expect(answered(2)).toBeVisible();
	await expect(status).toHaveText(/Tersimpan di server/);

	// Bukti dari server, bukan dari perangkat: antrean kosong lalu dimuat ulang.
	await page.evaluate(() => indexedDB.deleteDatabase("localcbt-offline"));
	await page.reload();
	await expect(answered(2)).toBeVisible();
});
