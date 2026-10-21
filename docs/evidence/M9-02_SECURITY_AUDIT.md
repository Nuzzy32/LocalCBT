# M9-02 Audit Keamanan

**Tanggal:** 21 Oktober 2026 · **Status:** semua temuan kritis/tinggi/sedang **diperbaiki**
dengan tes regresi. Beberapa sisa risiko butuh keputusan atau perangkat sekolah (lihat bawah).
Ini audit internal (kode + tes), **bukan** uji penetrasi pihak ketiga.

## Metode

- Empat audit paralel yang hanya membaca kode:
  1. autentikasi, sesi, CSRF, rate limit;
  2. otorisasi tingkat objek (BOLA/IDOR) per route;
  3. input tak tepercaya (import XLSX/DOCX, upload, XSS, ekspor, SQL);
  4. operasi dan infrastruktur (backup, CLI, Control Center, installer, CI, rahasia di repo).
- Setiap temuan dicocokkan ulang dengan kode sebelum diperbaiki. Untuk parser, temuan dibuktikan
  dengan berkas buatan.
- **Tes matriks akses** (`tests/test_route_access.py`): 80 route × 5 identitas (anonim, siswa,
  pengawas, guru, admin) dibandingkan dengan tabel kebijakan tertulis (PRD §11). Route baru yang
  belum diklasifikasikan membuat tes gagal. Tes ini juga menguji CSRF, Origin palsu/`null`, dan
  WebSocket monitor (anonim, Origin lain, siswa, guru yang bukan pengawas).
- Gitleaks atas seluruh riwayat git: bersih.

## Temuan & status

| # | Temuan | Tingkat | Status |
|---|---|---|---|
| 1 | XLSX 5 KB dengan nomor baris diklaim 10¹⁵ membuat worker macet tanpa batas (openpyxl menghasilkan setiap baris kosong). 24 upload = API mati saat ujian | **Tinggi** | Diperbaiki: batas baris fisik (5.000 soal / 10.000 siswa) dicek sebelum baris kosong dilewati, kolom dibatasi `max_col`. Berkas yang sama ditolak 413 dalam 3 ms |
| 2 | Service API & Caddy berjalan sebagai root (macOS) / LocalSystem (Windows) memakai kode yang bisa diubah user biasa → naik hak tanpa sudo | **Tinggi** | Diperbaiki: launchd `UserName` = user operator. Windows: folder program & `C:\LocalCBT` dikunci ACL Administrators+SYSTEM |
| 3 | Laporan probe jaringan bisa dipalsukan siswa → status "internet terblokir" hijau | Sedang | Diperbaiki: link probe sekali-putaran dari admin (kunci acak, 24 jam), laporan wajib memuat semua target, verdict = laporan **terburuk** satu putaran |
| 4 | `db.dump` belum terenkripsi ditulis di folder backup (bisa flashdisk FAT) dan tertinggal bila proses mati | Sedang | Diperbaiki: folder kerja 0700 di disk sistem; sisa folder kerja dibersihkan otomatis sebelum backup/restore berikutnya |
| 5 | DOCX 0,5 MB → 260 MB RAM saat parsing | Sedang | Diperbaiki: `document.xml` > 5 MB ditolak sebelum diparse; DOCX rusak → 422, bukan 500 |
| 6 | Windows: CA lokal Caddy & log terbaca/terubah semua user | Sedang | Diperbaiki (ACL, lihat #2) |
| 7 | `restore --switch` menyalin `.env` (kata sandi DB, kunci backup) dengan izin 0644 | Sedang | Diperbaiki: salinan & `.env` baru ditulis 0600 secara atomik |
| 8 | Batas percobaan login/token bisa diakali dengan permintaan paralel (token ujian minimal 4 karakter) | Rendah | Diperbaiki: cek & catat atomik; login benar tidak menghabiskan jatah (lab di balik NAT, 409 sesi aktif) |
| 9 | Sesi siswa tanpa batas diam: siswa berikutnya di komputer lab masuk sebagai siswa sebelumnya | Rendah | Diperbaiki: sesi siswa habis setelah diam 30 menit (`STUDENT_SESSION_IDLE_SECONDS`); staf tidak terpengaruh |
| 10 | Izin bank "Lihat" cukup untuk memasang gambar milik guru lain ke bank sendiri | Rendah | Diperbaiki: memasang gambar butuh pemilik/pengunggah atau izin minimal COPY |
| 11 | Tambah waktu menjalankan auto-submit sebelum mengecek hak pengawas | Rendah | Diperbaiki: hak dicek dulu |
| 12 | Nilai `.env` dari wizard bisa berubah diam-diam: `"` dibuang, `${VAR}` diekspansi python-dotenv **bahkan dalam kutip** → kata sandi backup service ≠ CLI ≠ yang dicatat | Rendah–sedang | Diperbaiki: pengutipan aman + `'`, `$`, baris baru ditolak; tes roundtrip memakai python-dotenv asli |
| 13 | `PUBLIC_HOST` masuk plist root tanpa validasi (injeksi XML) | Rendah | Diperbaiki: divalidasi di wizard & kedua installer |
| 14 | Parameter SQL (token CSRF, hash sandi, jawaban) ikut tercetak di log error | Rendah | Diperbaiki: `hide_parameters=True` |
| 15 | Penyamaran log melewatkan dict gaya Python & header `Authorization` | Rendah | Diperbaiki + tes |
| 16 | CI: token GitHub bisa tulis, kredensial tersimpan di checkout, image gitleaks `:latest` | Rendah | Diperbaiki: `permissions: contents: read`, `persist-credentials: false`, gitleaks dipin ke digest |
| 17 | scrypt N=2¹⁵ untuk kunci backup | Rendah | Diperbaiki: N=2¹⁷ (format `LCBK2`) |
| 18 | Swagger/OpenAPI terbuka tanpa login (juga dari jaringan siswa) | Rendah | Diperbaiki: mati secara default, `LOCALCBT_API_DOCS=true` untuk development |
| 19 | Panduan uji beban menyuruh menyalin folder berisi `.env` ke laptop di SSID siswa | Rendah | Diperbaiki di ADMIN_GUIDE §11 |
| 20 | `start_grant` yang aneh menghasilkan 500 | Info | Diperbaiki → ditolak biasa |
| 21 | Tes lama "semua route butuh login" ternyata kosong sejak FastAPI 0.14x (`app.routes` tidak memuat router yang di-include) | Proses | Diganti tes matriks akses |

## Yang sudah diperiksa dan aman (ringkas)

- **Sesi & login:**
  - token acak 256 bit, hanya hash SHA-256 yang disimpan;
  - cookie HttpOnly + Secure + SameSite=Strict;
  - CSRF per sesi dicek di setiap mutasi, ditambah cek Origin;
  - tidak ada enumerasi akun: hash dummy, pesan seragam;
  - IP tidak bisa dipalsukan lewat `X-Forwarded-For`: uvicorn hanya percaya Caddy di 127.0.0.1.
- **Otorisasi objek:**
  - guru tidak bisa menjangkau bank, ujian, hasil, atau ekspor guru lain;
  - pengawas tidak pernah menerima kunci, jawaban, atau nilai;
  - siswa tidak menjangkau attempt siswa lain, dan kunci tidak pernah ada di payload siswa sebelum diizinkan;
  - objek yang tidak boleh dilihat menjawab 404, bukan 403.
- **Input:**
  - XXE dan billion-laughs ditolak (defusedxml);
  - zip bomb dibatasi;
  - upload gambar memakai magic bytes, disajikan dengan `nosniff` + `CSP sandbox`;
  - tidak ada `dangerouslySetInnerHTML`;
  - ekspor XLSX memakai `inlineStr` tanpa formula;
  - semua SQL f-string hanya menyisipkan konstanta atau nama yang sudah divalidasi.
- **Backup:**
  - AES-GCM: nonce unik, AAD mengikat urutan dan frame final;
  - `unpack` menolak path traversal, symlink, dan berkas khusus;
  - nama DB untuk restore divalidasi;
  - prune tidak bisa keluar dari `backup_dir`.

## Sisa risiko & keputusan terbuka

- **Akun service khusus:** service sekarang berjalan sebagai user operator, bukan root. Ini
  menutup jalur naik hak, tetapi RCE di API tetap mendapat hak user operator. Akun khusus
  (`_localcbt` / `NT SERVICE\LocalCBT-API`) dengan folder program milik root disarankan untuk
  paket rilis. Script Windows belum diuji di Windows asli.
- **Izin "Lihat" menampilkan kunci jawaban** ke guru penerima. Ini sesuai desain saat ini
  (API_SPEC, tes); bila sekolah ingin "Lihat" tanpa kunci, perlu keputusan produk.
- **Biaya Argon2 di CPU lemah** (lihat M9-03): keputusan parameter menunggu uji di server sekolah.
- **Tidak diuji di sini:**
  - TLS/sertifikat di HP siswa (ADR-003, OQ-08);
  - blokir IPv4/IPv6 di router nyata. Probe + checklist sudah tersedia, tetapi bukti butuh
    jaringan sekolah;
  - uji penetrasi independen.
- **Rate limiter di memori** reset saat restart. Cukup untuk satu proses; perlu tabel DB bila
  uvicorn > 1 worker.
