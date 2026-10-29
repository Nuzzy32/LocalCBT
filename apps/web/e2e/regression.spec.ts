import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import {
	type Account,
	ADMIN,
	answerAll,
	checkA11y,
	EXAM,
	localInput,
	login,
	logout,
	STUDENTS_XLSX,
	saveState,
	TOKEN,
} from "./helpers";

// Alur utama lewat UI, berurutan: admin → guru → siswa → pengawas → hasil.
test.describe.configure({ mode: "serial" });

const teacher: Account = { username: "guru.e2e", password: "" };
const proctor: Account = { username: "pengawas.e2e", password: "" };
let students: Account[] = [];
let page: Page;

test.beforeAll(async ({ browser }) => {
	page = await (await browser.newContext()).newPage(); // axe butuh context sendiri
});
test.afterAll(() => page.context().close());

const region = (name: string) => page.getByRole("region", { name });

async function createStaff(who: Account, name: string, role: string) {
	const staff = region("Guru & pengawas");
	await staff.getByLabel("Username").fill(who.username);
	await staff.getByLabel("Nama lengkap").fill(name);
	await staff.getByLabel(role).check();
	await staff.getByRole("button", { name: "Buat akun" }).click();
	who.password = (await staff.locator("code.secret").textContent()) ?? "";
	expect(who.password).not.toBe("");
	await staff.getByRole("button", { name: "Sudah dicatat" }).click();
}

test("login gagal menampilkan pesan dan halaman login aksesibel", async () => {
	await page.goto("/");
	await checkA11y(page, "login");
	await page.getByLabel("NIS / Username").fill(ADMIN.username);
	await page.getByLabel("Kata sandi").fill("salah-sandi-123");
	await page.getByRole("button", { name: "Masuk" }).click();
	await expect(page.getByRole("alert")).toBeVisible();
});

test("admin: kelas, mapel, akun staf, penugasan, import siswa", async () => {
	await login(page, ADMIN);
	await expect(
		page.getByRole("heading", { name: "Administrasi" }),
	).toBeVisible();
	await checkA11y(page, "admin");

	const kelas = region("Kelas");
	await kelas.getByLabel("Kode").fill("IX-A");
	await kelas.getByLabel("Nama kelas").fill("Kelas IX A");
	await kelas.getByLabel("Tahun ajaran").fill("2026/2027");
	await kelas.getByRole("button", { name: "Tambah kelas" }).click();
	await expect(kelas.getByText("Kelas ditambahkan.")).toBeVisible();

	const mapel = region("Mata pelajaran");
	await mapel.getByLabel("Kode").fill("MTK");
	await mapel.getByLabel("Nama").fill("Matematika");
	await mapel.getByRole("button", { name: "Tambah mapel" }).click();
	await expect(mapel.getByText("Mata pelajaran ditambahkan.")).toBeVisible();

	await createStaff(teacher, "Bu Guru E2E", "Guru");
	await createStaff(proctor, "Pak Pengawas E2E", "Pengawas");

	const tugas = region("Penugasan mengajar");
	await tugas.getByLabel("Guru").selectOption({ label: "Bu Guru E2E" });
	await tugas.getByLabel("Kelas").selectOption({ label: "IX-A (2026/2027)" });
	await tugas.getByLabel("Mapel").selectOption({ label: "Matematika" });
	await tugas.getByRole("button", { name: "Tugaskan" }).click();
	await expect(tugas.getByText("Guru ditugaskan.")).toBeVisible();

	const imp = region("Import siswa");
	await imp.getByLabel("Berkas siswa").setInputFiles(STUDENTS_XLSX);
	await imp.getByRole("button", { name: "Periksa berkas" }).click();
	await expect(imp.getByText("5 dari 5 baris valid.")).toBeVisible();
	await checkA11y(page, "admin-import-preview");
	const download = page.waitForEvent("download");
	await imp.getByRole("button", { name: "Simpan 5 baris" }).click();
	const csv = readFileSync(await (await download).path(), "utf8");
	students = csv
		.split("\r\n")
		.slice(1)
		.map((line) => line.split(",").map((c) => c.replace(/^"|"$/g, "")))
		.map(([nis, , , password]) => ({ username: nis, password }));
	expect(students.map((s) => s.username)).toEqual([
		"001",
		"002",
		"003",
		"004",
		"005",
	]);
	const [, iphone, android, keyboard, offline] = students;
	saveState({ iphone, android, keyboard, offline });
	await logout(page);
});

test("guru: bank soal dengan tiga jenis soal", async () => {
	await login(page, teacher);
	await expect(page.getByRole("heading", { name: "Guru" })).toBeVisible();
	const baru = region("Bank soal baru");
	await baru.getByLabel("Judul").fill("Bank E2E");
	await baru.getByLabel("Mata pelajaran").selectOption({ label: "Matematika" });
	await baru.getByRole("button", { name: "Buat bank" }).click();
	await expect(page.getByRole("heading", { name: "Bank E2E" })).toBeVisible();

	let count = 0;
	const add = async (fill: () => Promise<void>) => {
		await page.getByRole("button", { name: "Tambah soal" }).click();
		await fill();
		await page.getByRole("button", { name: "Simpan soal" }).click();
		// Tunggu simpan selesai (jumlah soal naik), bukan tombolnya: selama menyimpan labelnya
		// "Menyimpan…" sehingga "Simpan soal" sudah tak terlihat (race di runner CI yang lambat).
		await expect(page.getByText(`· ${++count} soal ·`)).toBeVisible();
	};
	await add(async () => {
		await page.getByLabel("Pertanyaan").fill("Ibu kota Indonesia adalah …");
		for (const [i, text] of [
			"Jakarta",
			"Bandung",
			"Surabaya",
			"Medan",
		].entries())
			await page.getByLabel(`Opsi ${"ABCD"[i]}`).fill(text);
		await page.getByLabel("Kunci").first().check();
		await checkA11y(page, "guru-editor-soal");
	});
	await add(async () => {
		await page
			.getByLabel("Jenis soal")
			.selectOption({ label: "Pilihan Ganda Kompleks" });
		await page.getByLabel("Pertanyaan").fill("Pilih semua bilangan prima");
		for (const [i, text] of ["2", "3", "4", "9"].entries())
			await page.getByLabel(`Opsi ${"ABCD"[i]}`).fill(text);
		await page.getByLabel("Kunci").nth(0).check();
		await page.getByLabel("Kunci").nth(1).check();
	});
	await add(async () => {
		await page
			.getByLabel("Jenis soal")
			.selectOption({ label: "Benar/Salah per Pernyataan" });
		await page.getByLabel("Pertanyaan").fill("Tentukan benar atau salah");
		await page.getByLabel("Pernyataan 1").fill("1 + 1 = 2");
		await page.getByLabel("Pernyataan 2").fill("2 + 2 = 5");
		await page.getByRole("radio", { name: "Salah" }).nth(1).check();
	});
	await expect(page.getByText("3 soal")).toBeVisible();
	await checkA11y(page, "guru-bank");
});

test("guru: buat, publish, dan tugaskan pengawas", async () => {
	await page.getByRole("link", { name: "Ujian" }).click();
	await page.getByRole("button", { name: "Buat ujian" }).click();
	await page.getByLabel("Judul").fill(EXAM);
	await page.getByLabel("Mata pelajaran").selectOption({ label: "Matematika" });
	await page.getByLabel("IX-A · Kelas IX A").check();
	await page.getByLabel("Mulai dibuka").fill(await localInput(page, -5));
	await page.getByLabel("Batas akhir mulai").fill(await localInput(page, 120));
	await page.getByLabel("Token ujian").fill(TOKEN);
	await page.getByLabel("Langsung setelah siswa mengumpulkan").check();
	await page.getByLabel("Buka pembahasan").check();
	await page.getByText("Bank E2E").click();
	const boxes = page.locator(".pick-row input");
	await expect(boxes).toHaveCount(3); // soal dimuat saat bank dibuka
	for (const box of await boxes.all()) await box.check();
	await expect(
		page.getByRole("heading", { name: "Soal (3 dipilih)" }),
	).toBeVisible();
	await checkA11y(page, "guru-form-ujian");
	await page.getByRole("button", { name: "Simpan draft" }).click();

	await page.getByRole("button", { name: "Publish…" }).click();
	const dialog = page.getByRole("dialog");
	await dialog.getByRole("checkbox").check();
	await checkA11y(page, "guru-dialog-publish");
	await dialog.getByRole("button", { name: "Publish & bekukan soal" }).click();
	await expect(
		page.getByText("Ujian dipublish dan soal sudah dibekukan."),
	).toBeVisible();

	const pengawas = region("Pengawas");
	await pengawas
		.getByLabel("Tugaskan pengawas")
		.selectOption({ label: "Pak Pengawas E2E" });
	await pengawas.getByRole("button", { name: "Tugaskan" }).click();
	await expect(pengawas.getByText("Pak Pengawas E2E")).toBeVisible();
	await checkA11y(page, "guru-detail-ujian");
	await logout(page);
});

test("siswa (desktop): token, menjawab, tandai, kumpulkan, nilai, pembahasan", async () => {
	await login(page, students[0]);
	await expect(page.getByText(EXAM)).toBeVisible();
	await checkA11y(page, "siswa-daftar");
	await page.getByRole("button", { name: "Mulai" }).click();

	await page.getByLabel("Token ujian dari pengawas").fill("SALAH999");
	await page.getByRole("button", { name: "Lanjut" }).click();
	await expect(page.getByRole("alert")).toBeVisible();
	await page.getByLabel("Token ujian dari pengawas").fill(TOKEN);
	await page.getByRole("button", { name: "Lanjut" }).click();
	await page.getByLabel("Saya sudah membaca petunjuk").check();
	await checkA11y(page, "siswa-petunjuk");
	await page.getByRole("button", { name: "Mulai ujian" }).click();

	await answerAll(page);
	await page.getByRole("button", { name: "Tandai untuk ditinjau" }).click();
	await expect(
		page.getByRole("button", { name: /ditandai/ }).first(),
	).toBeVisible();
	await expect(page.getByText(/Tersimpan di server/)).toBeVisible();
	await checkA11y(page, "siswa-soal");

	// Muat ulang di tengah ujian: jawaban tetap ada (dari server).
	await page.reload();
	await expect(page.getByText("Terjawab 3 / 3").first()).toBeVisible();

	await page.getByRole("button", { name: "Kumpulkan ujian" }).click();
	await checkA11y(page, "siswa-dialog-kumpulkan");
	await page.getByRole("button", { name: "Ya, kumpulkan" }).click();
	await expect(
		page.getByRole("heading", { name: "Ujian berhasil dikumpulkan." }),
	).toBeVisible();
	await expect(page.getByText(/Nilai: 3(,0+)? dari 3/)).toBeVisible();
	await page.getByRole("button", { name: "Lihat pembahasan" }).click();
	// Kunci tidak dibuka selama jendela ujian masih berjalan (peserta lain bisa mulai).
	await expect(
		page.getByText("Pembahasan belum dibuka oleh guru."),
	).toBeVisible();
	await checkA11y(page, "siswa-bukti-pembahasan");
	await page.getByRole("button", { name: "Kembali ke daftar ujian" }).click();
	await expect(page.getByRole("button", { name: "Lihat bukti" })).toBeVisible();
	await logout(page);
});

test("pengawas: pantau peserta dan kirim pengumuman", async () => {
	await login(page, proctor);
	await expect(page.getByRole("heading", { name: "Pengawasan" })).toBeVisible();
	await page.getByRole("button", { name: "Pantau" }).click();
	await expect(page.getByRole("cell", { name: "Siswa E2E 1" })).toBeVisible();
	await page
		.getByLabel("Pesan untuk semua peserta")
		.fill("Periksa kembali jawaban Anda.");
	await page.getByRole("button", { name: "Kirim pengumuman" }).click();
	await expect(page.getByText(/Periksa kembali jawaban Anda/)).toBeVisible();
	await checkA11y(page, "pengawas-monitor");
	await logout(page);
});

test("guru: hasil & nilai menampilkan siswa yang sudah mengumpulkan", async () => {
	await login(page, teacher);
	await page.getByRole("link", { name: "Ujian" }).click();
	await page.getByRole("button", { name: "Detail" }).click();
	await page.getByRole("button", { name: "Hasil & nilai" }).click();
	const row = page.getByRole("row", { name: /Siswa E2E 1/ });
	await expect(row).toContainText("3");
	await checkA11y(page, "guru-hasil");
});
