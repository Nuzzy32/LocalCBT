# M9-01 Regresi Penuh, Aksesibilitas & Mobile

**Tanggal:** 28 Oktober 2026 · **Status:** semua tes otomatis LULUS di mesin pengembangan dan
dijalankan ulang di CI tiap push (job `e2e`). Belum diuji di ponsel fisik maupun dengan pembaca
layar sungguhan (lihat "Belum dibuktikan").

## Hasil

| Lapisan (DEVELOPMENT_PLAN M9-01) | Cara uji | Hasil |
|---|---|---|
| Unit & integrasi API | `pytest` (PostgreSQL sungguhan) | **LULUS** 243 tes |
| Kontrak API | `tests/test_contract.py`: setiap path+method di `docs/API_SPEC.yaml` ada di server dan sebaliknya | **LULUS** 79 endpoint (setelah perbaikan temuan 1) |
| Control Center | `pytest` (Qt offscreen) | **LULUS** 10 tes |
| E2E desktop | `apps/web/e2e/regression.spec.ts` (Chromium, hanya lewat UI): admin membuat kelas, mapel, akun guru/pengawas, penugasan, lalu import 5 siswa dari .xlsx. Guru membuat bank soal dengan 3 jenis soal, lalu ujian (publish, tugaskan pengawas). Siswa salah token lalu benar, menjawab, menandai soal, reload di tengah ujian, kumpulkan, nilai 3/3. Pengawas memantau dan mengirim pengumuman. Guru melihat hasil | **LULUS** 7 tes |
| Mobile | `mobile.spec.ts` di **iPhone 13 (WebKit, 390 px)** dan **Android (Chromium, 360 px)**: alur siswa penuh lewat lembar "Nomor soal" (UX-02), rotasi ke lanskap, reflow 320 px | **LULUS** 2 perangkat (setelah perbaikan temuan 2) |
| Aksesibilitas otomatis | axe-core, tag WCAG 2.0/2.1/2.2 A+AA, di 15 layar desktop dan 7 layar × 2 ponsel (29 pemindaian) | **LULUS** 0 pelanggaran |
| Touch target | Semua kontrol terlihat di layar siswa ponsel ≥ 44×44 px (DESIGN_SYSTEM; radio/checkbox diukur dari labelnya) | **LULUS** |
| Tanpa clipping | Tidak ada elemen keluar dari layar, termasuk di area yang punya scroll sendiri, pada 390, 360, 320 px dan lanskap | **LULUS** (setelah perbaikan temuan 2) |
| Keyboard saja | `keyboard.spec.ts`: login sampai kumpulkan hanya dengan Tab/panah/Spasi/Enter/Esc. Fokus terlihat (`:focus-visible` + outline), fokus tertahan di dialog, Esc menutup dialog dan mengembalikan fokus ke pemicu | **LULUS** (setelah perbaikan temuan 3) |
| Antrean offline di browser (sisa M9-04) | `offline.spec.ts`. Perangkat offline: jawaban masuk IndexedDB, status "tersimpan di perangkat, belum tersinkron", peringatan koneksi tampil, tombol kumpulkan dikunci; lalu online dan tersinkron otomatis. API terputus lalu halaman dimuat ulang: antrean dikirim ulang. Bukti diambil dari server setelah IndexedDB dihapus | **LULUS** |

Screenshot setiap layar ponsel tersimpan di `apps/web/e2e/.tmp/screens/` (CI: artifact
`e2e-report`).

## Temuan & perbaikan

1. **Spec API tertinggal dari server (diperbaiki).** `GET /admin/students`,
   `GET /admin/interventions`, dan `GET /healthz` sudah dipakai web/installer tapi tidak ada di
   `API_SPEC.yaml`. Ketiganya sekarang didokumentasikan. `test_contract.py` menggagalkan CI
   bila spec dan server berbeda lagi.
2. **Lembar "Nomor soal" terpotong di ponsel (diperbaiki).** Lembarnya 50 px lebih lebar dari
   layar (410 px di layar 360 px, 440 px di iPhone 390 px), sehingga sisi kanan nomor soal dan
   legenda terpotong. Penyebabnya `.dialog` memakai `content-box`: lebar `100%` masih ditambah
   padding dan border. Perbaikan: `box-sizing: border-box`.
3. **Fokus tidak pindah ke konfirmasi setelah mengumpulkan (diperbaiki).** Halaman bukti memanggil
   `focus()` pada judul "Ujian berhasil dikumpulkan." sebelum data attempt termuat, saat judul itu
   belum ada. Akibatnya pengguna pembaca layar tidak mendengar konfirmasi. Fokus kini dipindah
   setelah attempt termuat.
4. **Bukan bug: kontras diukur di tengah animasi.** axe sempat melaporkan kontras 1,74:1 pada
   tombol "Ditandai" karena warnanya diukur saat transisi 150 ms. Warna akhirnya (#155e75 di atas
   putih) memenuhi AA. Tes kini memakai `prefers-reduced-motion: reduce`, yang juga menguji jalur
   gerak-dikurangi.

**Detektor terbukti bisa gagal.** Setiap pemeriksaan sengaja dirusak sekali sebelum dipercaya:
kontras teks diturunkan (axe gagal `color-contrast`), tombol dikecilkan ke 20 px (gagal touch
target di 4 layar), dan konten dilebarkan (gagal "keluar layar"). Uji mutasi ketiga ini juga yang
membongkar temuan 2: versi pertama pemeriksaan hanya membandingkan lebar halaman, sehingga
melewatkan konten yang meluber di dalam area soal yang punya scroll sendiri.

## Belum dibuktikan

- **Ponsel fisik di jaringan sekolah.** Emulasi Playwright memakai engine yang sama (WebKit,
  Chromium), tetapi tidak menguji Safari/Chrome asli, keyboard virtual yang menutupi input,
  maupun kepercayaan sertifikat HTTPS lokal (DISC-04, ADR-003 masih OPEN). Masuk pilot M9-05.
- **Pembaca layar sungguhan** (VoiceOver iOS, TalkBack, NVDA). axe hanya menangkap sebagian
  kriteria WCAG. Label, peran, live region timer, dan urutan fokus sudah diperiksa otomatis,
  tetapi pengalaman mendengarkannya belum.
- **Zoom teks 200% dari pengaturan browser.** Reflow 320 px setara zoom 400% pada layar 1280 px
  untuk tata letak, tetapi pengaturan ukuran teks OS/browser belum diuji.
- **Jalur keyboard halaman staf** (admin, guru, pengawas). Baru diuji dengan axe (label, peran,
  kontras) dan alur mouse. Jalur keyboard penuh otomatis baru untuk siswa.
- **Pembahasan saat terbuka.** Di E2E pembahasan masih tertutup karena jendela ujian belum
  berakhir (perilaku yang benar). Isi pembahasan diuji di `tests/test_attempts.py`.
- **Firefox, Edge, dan tablet 768 px** tidak masuk matriks otomatis.

## Menjalankan ulang

```bash
docker compose -f compose.dev.yml up -d           # PostgreSQL dev
cd apps/web
pnpm exec playwright install chromium webkit      # sekali
pnpm e2e                                          # DB localcbt_e2e dibuat ulang tiap run
```

`e2e/api.sh` menjalankan API di port 8200 dan Vite di port 5174, jadi server dev biasa
(8000/5173) tidak terganggu. Jangan arahkan `localcbt_e2e` ke database lain: database itu
dihapus setiap run.
