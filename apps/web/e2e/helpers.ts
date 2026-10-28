import { readFileSync, writeFileSync } from "node:fs";
import { AxeBuilder } from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// Nilai uji saja (database localcbt_e2e dibuat ulang tiap run).
export const ADMIN = { username: "admin", password: "admin-e2e-rahasia" };
export const TOKEN = "UJIE2E01";
export const EXAM = "Ulangan Harian E2E";
export const STUDENTS_XLSX = `${import.meta.dirname}/.tmp/students.xlsx`;
const STATE = `${import.meta.dirname}/.tmp/state.json`;

export type Account = { username: string; password: string };
export type State = Record<string, Account>; // nama proyek Playwright → akun siswa

export const saveState = (s: State) => writeFileSync(STATE, JSON.stringify(s));
export const loadState = (): State => JSON.parse(readFileSync(STATE, "utf8"));

export async function login(page: Page, who: Account) {
	await page.goto("/");
	await page.getByLabel("NIS / Username").fill(who.username);
	await page.getByLabel("Kata sandi").fill(who.password);
	await page.getByRole("button", { name: "Masuk" }).click();
	await expect(page.getByRole("button", { name: "Masuk" })).toBeHidden();
}

export async function logout(page: Page) {
	await page.getByRole("button", { name: "Keluar" }).click();
	await expect(page.getByRole("button", { name: "Masuk" })).toBeVisible();
}

/** WCAG 2.2 A/AA lewat axe-core; pelanggaran dilampirkan ke laporan lalu menggagalkan tes. */
export async function checkA11y(page: Page, screen: string) {
	const { violations } = await new AxeBuilder({ page })
		.withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
		.analyze();
	const summary = violations.map((v) => ({
		rule: v.id,
		impact: v.impact,
		help: v.help,
		nodes: v.nodes.map((n) => ({
			target: n.target.join(" "),
			failure: n.failureSummary,
		})),
	}));
	if (summary.length) {
		await test.info().attach(`a11y-${screen}`, {
			body: JSON.stringify(summary, null, 2),
			contentType: "application/json",
		});
	}
	expect.soft(summary, `aksesibilitas: ${screen}`).toEqual([]);
}

/** Layar ponsel: tidak ada elemen yang keluar dari layar (terpotong atau memaksa geser horizontal),
 * termasuk di dalam area yang punya scroll sendiri. Tabel (.table-wrap) memang boleh digeser. */
export async function expectNoHorizontalScroll(page: Page, screen: string) {
	const outside = await page.evaluate(() =>
		[...document.querySelectorAll<HTMLElement>("body *")]
			.filter((el) => el.checkVisibility() && !el.closest(".table-wrap"))
			.flatMap((el) => {
				const r = el.getBoundingClientRect();
				if (r.width === 0 || (r.left >= -1 && r.right <= window.innerWidth + 1))
					return [];
				return `${el.tagName.toLowerCase()}.${el.className} ${Math.round(r.left)}–${Math.round(r.right)}`;
			}),
	);
	expect
		.soft(
			outside,
			`keluar layar (${await page.evaluate(() => window.innerWidth)}px): ${screen}`,
		)
		.toEqual([]);
}

/** DESIGN_SYSTEM: touch target minimal 44×44 px. Radio/checkbox diukur dari label pembungkusnya. */
export async function expectTouchTargets(page: Page, screen: string) {
	const small = await page.evaluate(() =>
		[
			...document.querySelectorAll<HTMLElement>(
				"button, a[href], select, textarea, input:not([type=hidden])",
			),
		]
			.map((el) =>
				el.matches("[type=radio], [type=checkbox]")
					? (el.closest("label") ?? el)
					: el,
			)
			.filter((el) => el.checkVisibility())
			.flatMap((el) => {
				const { width, height } = el.getBoundingClientRect();
				if (width >= 44 && height >= 44) return [];
				const name =
					el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 40);
				return `${el.tagName.toLowerCase()} "${name}" ${Math.round(width)}×${Math.round(height)}`;
			}),
	);
	expect.soft(small, `touch target < 44px: ${screen}`).toEqual([]);
}

/** "2026-10-28T13:05" di zona waktu browser (untuk input datetime-local). */
export function localInput(page: Page, offsetMinutes: number) {
	return page.evaluate((m) => {
		const d = new Date(Date.now() + m * 60_000);
		d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
		return d.toISOString().slice(0, 16);
	}, offsetMinutes);
}

/** Jawab semua soal dengan benar; urutan soal & opsi diacak per siswa. */
export async function answerAll(page: Page, viaSheet = false) {
	for (let i = 0; i < 3; i++) {
		const q = page.locator("article.question");
		const stem = await q.locator(".stem").textContent();
		if (stem?.startsWith("Ibu kota")) {
			await q.getByRole("radio", { name: /Jakarta$/ }).check();
		} else if (stem?.startsWith("Pilih semua")) {
			await q.getByRole("checkbox", { name: /\. 2$/ }).check();
			await expect(page.getByText(/Tersimpan di server/)).toBeVisible();
			await q.getByRole("checkbox", { name: /\. 3$/ }).check();
		} else {
			await q
				.getByRole("group", { name: "1 + 1 = 2" })
				.getByLabel("Benar")
				.check();
			await q
				.getByRole("group", { name: "2 + 2 = 5" })
				.getByLabel("Salah")
				.check();
		}
		await expect(page.getByText(/Tersimpan di server/)).toBeVisible();
		if (i < 2) {
			if (viaSheet) {
				await page.getByRole("button", { name: "Nomor soal" }).click();
				await page
					.getByRole("dialog")
					.getByRole("button", { name: `Nomor ${i + 2},` })
					.click();
			} else {
				await page.getByRole("button", { name: "Berikutnya →" }).click();
			}
		}
	}
}
