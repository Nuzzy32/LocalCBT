import { expect, type Locator, type Page, test } from "@playwright/test";
import { EXAM, loadState, TOKEN } from "./helpers";

// UI_UX: "Navigasi keyboard lengkap, fokus terlihat"; ConfirmDialog menjebak fokus, Esc batal.
// Hanya Tab/panah/Spasi/Enter/Esc: tidak ada klik mouse sama sekali.

/** Tekan Tab sampai `target` terfokus; gagal bila tidak terjangkau keyboard. */
async function tabTo(page: Page, target: Locator) {
	for (let i = 0; i < 60; i++) {
		if (await target.evaluate((el) => el === document.activeElement)) {
			const visible = await target.evaluate((el) => {
				const s = getComputedStyle(el);
				return el.matches(":focus-visible") && s.outlineStyle !== "none";
			});
			expect.soft(visible, `fokus terlihat: ${target}`).toBe(true);
			return;
		}
		await page.keyboard.press("Tab");
	}
	throw new Error(`tidak terjangkau dengan Tab: ${target}`);
}

/** Radio dalam satu grup: Tab ke grup, lalu panah sampai `target` terpilih. */
async function arrowTo(page: Page, group: Locator, target: Locator) {
	await tabTo(page, group.getByRole("radio").first());
	for (let i = 0; i < 6 && !(await target.isChecked()); i++)
		await page.keyboard.press(i === 0 ? "Space" : "ArrowDown");
	await expect(target).toBeChecked();
}

test("siswa: seluruh ujian hanya dengan keyboard", async ({ page }) => {
	const student = loadState().keyboard;
	const saved = page.getByText(/Tersimpan di server/);
	await page.goto("/");

	await tabTo(page, page.getByLabel("NIS / Username"));
	await page.keyboard.type(student.username);
	await tabTo(page, page.getByLabel("Kata sandi"));
	await page.keyboard.type(student.password);
	await page.keyboard.press("Enter");
	await expect(page.getByText(EXAM)).toBeVisible();

	await tabTo(page, page.getByRole("button", { name: "Mulai" }));
	await page.keyboard.press("Enter");
	await tabTo(page, page.getByLabel("Token ujian dari pengawas"));
	await page.keyboard.type(TOKEN);
	await page.keyboard.press("Enter");
	await tabTo(page, page.getByLabel("Saya sudah membaca petunjuk"));
	await page.keyboard.press("Space");
	await tabTo(page, page.getByRole("button", { name: "Mulai ujian" }));
	await page.keyboard.press("Enter");

	for (let i = 0; i < 3; i++) {
		const q = page.locator("article.question");
		const stem = (await q.locator(".stem").textContent()) ?? "";
		if (stem.startsWith("Ibu kota")) {
			await arrowTo(page, q, q.getByRole("radio", { name: /Jakarta$/ }));
		} else if (stem.startsWith("Pilih semua")) {
			for (const name of [/\. 2$/, /\. 3$/]) {
				await tabTo(page, q.getByRole("checkbox", { name }));
				await page.keyboard.press("Space");
				await expect(saved).toBeVisible();
			}
		} else {
			for (const [statement, value] of [
				["1 + 1 = 2", "Benar"],
				["2 + 2 = 5", "Salah"],
			]) {
				const group = q.getByRole("group", { name: statement });
				await arrowTo(page, group, group.getByLabel(value));
			}
		}
		await expect(saved).toBeVisible();
		if (i < 2) {
			await tabTo(page, page.getByRole("button", { name: "Berikutnya →" }));
			await page.keyboard.press("Enter");
		}
	}
	await expect(page.getByText("Terjawab 3 / 3").first()).toBeVisible();

	const open = page.getByRole("button", { name: "Kumpulkan ujian" });
	const dialog = page.getByRole("dialog", { name: "Kumpulkan ujian?" });
	await tabTo(page, open);
	await page.keyboard.press("Enter");
	await expect(dialog).toBeVisible();
	const focusInDialog = () =>
		page.evaluate(() => Boolean(document.activeElement?.closest("dialog")));
	expect(await focusInDialog(), "fokus pindah ke dialog").toBe(true);
	for (let i = 0; i < 6; i++) {
		await page.keyboard.press("Tab");
		const inside = await focusInDialog();
		const onBody = await page.evaluate(
			() => document.activeElement === document.body,
		);
		// Tab melewati akhir dialog boleh singgah di UI browser (body), tidak ke belakang dialog.
		expect(inside || onBody, "fokus tetap dalam dialog").toBe(true);
	}
	await page.keyboard.press("Escape");
	await expect(dialog).toBeHidden();
	await expect(open, "fokus kembali ke tombol pemicu").toBeFocused();

	await page.keyboard.press("Enter");
	await tabTo(page, dialog.getByRole("button", { name: "Ya, kumpulkan" }));
	await page.keyboard.press("Enter");
	const done = page.getByRole("heading", {
		name: "Ujian berhasil dikumpulkan.",
	});
	await expect(done).toBeVisible();
	// Pembaca layar langsung mendengar konfirmasi: fokus pindah ke judul bukti.
	await expect(done).toBeFocused();
});
