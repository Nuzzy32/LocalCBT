# Panduan Administrator & Operator — LocalCBT

Panduan ini untuk operator yang memasang dan merawat server LocalCBT di sekolah: instalasi,
jaringan ujian, backup, restore, pembaruan versi, dan penanganan gangguan.
Panduan guru ada di [TEACHER_QUICKSTART.md](TEACHER_QUICKSTART.md), panduan pengawas di
[PROCTOR_SOP.md](PROCTOR_SOP.md).

Prinsip yang tidak boleh dilanggar:
- **Ujian tidak bergantung internet.** Semua halaman, gambar, dan data ada di server sekolah.
- **Backup baru dianggap ada bila "VERIFIED"** dan sudah pernah lulus **Uji restore**.
- **Restore tidak pernah menimpa database yang sedang dipakai.** Restore selalu ke database baru;
  database lama disimpan sampai Anda yakin.
- **Kata sandi backup = kunci semua backup.** Bila hilang, backup tidak bisa dibuka oleh siapa pun.

---

## 1. Yang perlu disiapkan

| Komponen | Keterangan |
|---|---|
| Komputer server | Windows 10/11 atau macOS, menyala selama ujian, sebaiknya dengan UPS. Spesifikasi minimal belum ditetapkan (DEC-07): uji beban dulu sebelum pilot. |
| PostgreSQL 16 | Windows: installer EDB. macOS: Postgres.app atau Homebrew `postgresql@16`. Versi klien `pg_dump`/`pg_restore` **harus sama** dengan versi server (preflight memeriksa ini). |
| uv | Pengelola Python untuk menjalankan API. |
| Caddy | HTTPS portal. Windows: `caddy.exe` di `infrastructure\windows\`. |
| WinSW (Windows) | `WinSW-x64.exe` disalin dua kali ke `infrastructure\windows\` sebagai `localcbt-api.exe` dan `localcbt-caddy.exe`. |
| Drive backup | Disk/flashdisk eksternal atau disk kedua. Jangan satu disk dengan data utama. |
| Router/AP | Mendukung SSID/VLAN terpisah untuk ujian dan staf, firewall IPv4 **dan** IPv6. |
| Sertifikat HTTPS | Strategi belum final (ADR-003, OQ-08). Jangan pernah meminta siswa mengabaikan peringatan sertifikat. |

Semua berkas di atas disiapkan **sebelum** hari pemasangan, karena server ujian tidak perlu
internet.

---

## 2. Pemasangan pertama

1. Salin folder LocalCBT (paket rilis, sudah berisi `apps/web/dist`) ke server.
2. Buat database dan akun PostgreSQL untuk LocalCBT, misalnya user `localcbt` dengan kata sandi kuat.
   Akun ini butuh hak `CREATEDB` agar **Uji restore** bisa membuat database sementara. Bila tidak
   boleh, isi `LOCALCBT_ADMIN_DATABASE_URL` (akun admin PostgreSQL) di lingkungan saat menjalankan CLI.
3. Buka **Control Center** → tab **Layanan** → **Setup awal…**:
   1. **Konfigurasi server**: URL database, alamat portal (mis. `cbt.sekolah.sch.id`), folder
      backup (drive terpisah), subnet jaringan ujian (mis. `10.20.0.0/22`), dan **kata sandi backup**.
      Tulis kata sandi backup di kertas, masukkan amplop tertutup, simpan di brankas sekolah.
      Isian ini disimpan di `services/api/.env` yang hanya bisa dibaca admin.
   2. **Siapkan database**: tekan **Jalankan migrasi database**.
   3. **Admin pertama**: nama pengguna, nama lengkap, kata sandi minimal 12 karakter.
   4. **Pasang service**: jalankan perintah yang ditampilkan sebagai administrator:
      - macOS: `sudo scripts/install-macos.sh`
      - Windows: `powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1`
4. Tutup Control Center, lalu buka `https://<alamat portal>` dari laptop staf. Portal harus tetap
   hidup walau Control Center ditutup (T-019).
5. **Restart komputer server** sekali, lalu pastikan portal kembali hidup sendiri.

> Script Windows belum diuji di mesin Windows asli. Uji di server target sebelum pilot.

---

## 3. Control Center

| Tab | Isi |
|---|---|
| **Ringkasan** | Status service, database, disk, CPU/RAM, jumlah ujian berjalan, backup terakhir, lokasi backup, status jaringan ujian, versi skema. Merah = perlu tindakan. |
| **Jaringan** | **Jalankan preflight**, hasil probe dari perangkat siswa, **Catat pemeriksaan manual…**. |
| **Backup & Restore** | **Backup sekarang**, **Uji restore**, **Restore…**, **Atur masa simpan…**, daftar backup. |
| **Log** | Log server dengan kata sandi, token, email, dan NISN disamarkan. **Ekspor…** untuk dikirim ke dukungan teknis. |
| **Layanan** | Start / Stop / Restart service, **Setup awal…**. |

Control Center memanggil perintah `python -m app.cli` di folder `services/api`, jadi tetap bisa
dipakai saat API mati. Semua perintah yang sama bisa dijalankan dari terminal (lihat §9).

---

## 4. Jaringan ujian

### 4.1 Aturan router (BR-24, FR-OPS-01)

| Dari | Ke | Aturan |
|---|---|---|
| SSID/VLAN ujian | Server LocalCBT port 443 | **Izinkan** |
| SSID/VLAN ujian | DNS & DHCP lokal | Izinkan (DNS hanya resolver lokal) |
| SSID/VLAN ujian | Internet (IPv4 **dan IPv6**) | **Blokir** |
| SSID/VLAN ujian | Jaringan staf, halaman admin router | **Blokir** |
| SSID/VLAN ujian | Perangkat siswa lain | Blokir (client isolation) bila didukung |
| Jaringan staf | Server LocalCBT port 443 | Izinkan |

Nama portal (mis. `cbt.sekolah.sch.id`) harus di-resolve DNS lokal ke IP server dari kedua jaringan.

### 4.2 Preflight sebelum hari ujian

1. Tab **Jaringan** → **Jalankan preflight**. Setiap baris berstatus **OK**, **WARNING**,
   **FAILED**, atau **UNTESTED**. UNTESTED berarti belum dibuktikan, bukan lulus.
2. Dari HP/laptop siswa yang tersambung ke **SSID ujian**, buka alamat probe yang tertera
   (`https://<portal>/api/v1/ops/probe`). Halaman mencoba menghubungi beberapa alamat internet
   dan melaporkan hasilnya ke server. Tidak ada data pribadi yang dikirim.
3. Baris **wan_blocked** menjadi **OK** hanya bila laporan datang dari subnet ujian, portal lokal
   terjangkau, **semua** alamat internet terblokir, dan umurnya kurang dari 7 hari.
4. Probe hanya membuktikan HTTPS ke internet tertutup dari browser. Periksa sisanya secara manual
   dari perangkat siswa (IPv6, DNS publik, akses ke jaringan staf, halaman admin router), lalu
   tekan **Catat pemeriksaan manual…**, centang yang benar-benar sudah diuji, dan isi nama pemeriksa.
   Catatan ini masuk audit.
5. Jam server harus tersinkron (NTP) sebelum ujian. Preflight tidak bisa membuktikannya.

### 4.3 Checklist pagi hari ujian

- [ ] Listrik/UPS siap, server menyala, **Ringkasan** tidak ada yang merah.
- [ ] Backup terakhir **OK** (kurang dari 36 jam) dan drive backup tersambung.
- [ ] Preflight dijalankan, probe jaringan ujian **OK** minggu ini.
- [ ] Satu akun siswa uji berhasil login, mulai, menjawab, dan mengumpulkan.
- [ ] Kontak operator diketahui semua pengawas.

---

## 5. Backup

### 5.1 Cara kerja

- **Backup harian otomatis** berjalan pada jam yang diatur (awal: 02.00) atau saat pertama server
  menyala sesudahnya, **asal tidak ada ujian berjalan**. Bila backup terverifikasi terakhir lebih
  dari 36 jam, backup dipaksa walau ada ujian (server sering mati di malam hari).
- **Backup manual**: tab **Backup & Restore** → **Backup sekarang**.
- Isi backup: seluruh database + semua gambar soal, dalam satu folder per backup:
  `manifest.json` (ringkasan tanpa data siswa) dan `data.lcbk` (terenkripsi AES-256).
- Setelah ditulis, backup **didekripsi ulang dan dicek**: setiap gambar dan berkas database harus
  cocok dengan sidik jarinya, dan `pg_restore` harus bisa membacanya. Baru setelah itu statusnya
  **VERIFIED**. Bila satu langkah gagal, statusnya **FAILED**, folder parsial dihapus, dan
  **Ringkasan** menampilkan alasannya dengan warna merah.
- Hanya satu backup/restore berjalan pada satu waktu.

### 5.2 Masa simpan

**Atur masa simpan…** menetapkan jam backup harian, jumlah backup harian yang disimpan, dan berapa
hari backup manual disimpan. Nilai awal 14 backup harian dan 90 hari adalah **usulan**; kebijakan
final ditetapkan pimpinan sekolah (OQ-07). Setiap perubahan wajib alasan dan masuk audit.
Backup terbaru yang terverifikasi tidak pernah dihapus otomatis.

Retensi nilai dan log ujian belum tersedia di versi ini, menunggu keputusan sekolah (OQ-07).

### 5.3 Salinan kedua

Arahkan folder backup ke drive yang berbeda dari data utama. Bila Control Center menampilkan
"satu disk dengan data utama", pindahkan `LOCALCBT_BACKUP_DIR`. Sebaiknya simpan juga salinan
mingguan di media yang disimpan di luar ruang server. Isi backup terenkripsi, jadi aman dibawa
asalkan kata sandinya tidak ikut.

### 5.4 Uji restore rutin (FR-OPS-06)

Minimal sebulan sekali dan setiap sebelum musim ujian: pilih backup VERIFIED → **Uji restore**.
Backup dipulihkan ke database sementara, jumlah datanya dicocokkan dengan backup, lalu database
sementara dihapus. Data asli tidak disentuh. Kolom **Uji restore** di tabel terisi bila lulus.

---

## 6. Restore (memulihkan data)

Pakai hanya bila database rusak atau data hilang. **Restore saat ujian berjalan dilarang**,
kecuali insiden kritis dengan izin pimpinan; alasan wajib diisi dan dicatat.

1. Pastikan tidak ada ujian berjalan (**Ringkasan** → Ujian berjalan = 0).
2. Tab **Backup & Restore**, pilih backup VERIFIED yang diinginkan → **Restore…**.
3. Isi nama database baru (sudah terisi otomatis), biarkan **Alihkan service** tercentang,
   isi alasan insiden bila diminta, ketik `PULIHKAN`, lalu OK.
4. Control Center memulihkan backup ke database baru, mencocokkan jumlah datanya, mengarahkan
   `.env` ke database baru (salinan `.env` lama disimpan sebagai `.env.bak-<waktu>`), lalu me-restart
   service.
5. Login sebagai admin dan periksa data. Ingat: semua perubahan **setelah** waktu backup tidak ada.
6. Database lama tetap ada. Hapus hanya setelah yakin, oleh admin PostgreSQL.

Untuk kembali ke database lama: kembalikan baris `LOCALCBT_DATABASE_URL` dari `.env.bak-<waktu>`,
lalu **Restart**.

---

## 7. Pembaruan versi

1. Pilih waktu tanpa ujian. Pembaruan **ditolak** bila ada ujian berjalan.
2. Ganti folder program dengan versi baru (folder `services/api/.env` dan backup jangan dihapus).
3. Jalankan sebagai administrator:
   - macOS: `sudo scripts/install-macos.sh --upgrade`
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -Upgrade`
4. Script membuat **backup PRE_UPGRADE** yang terverifikasi, menjalankan migrasi skema dalam satu
   transaksi (gagal = otomatis kembali), me-restart service, dan menunggu API sehat.
5. Bila API tidak sehat setelah pembaruan: pasang kembali versi lama, lalu restore backup
   PRE_UPGRADE (§6).

---

## 8. Gangguan & insiden

| Gejala | Tindakan |
|---|---|
| Ringkasan: Service **STOPPED** | Tab **Layanan** → **Start**. Bila gagal, buka tab **Log** → **Hanya error**. |
| Database **DOWN** | Periksa service PostgreSQL berjalan. Waktu server mati otomatis dikompensasi ke siswa (DEC-03). |
| Disk **WARNING/CRITICAL** | Kosongkan disk atau kurangi masa simpan backup. Di bawah 5% ujian berisiko gagal menyimpan jawaban. |
| Backup **GAGAL** | Baca pesannya. Penyebab umum: kata sandi backup belum diatur, drive backup tercabut, disk penuh, versi `pg_dump` tidak cocok. Perbaiki lalu **Backup sekarang**. |
| Probe jaringan **FAILED** | Internet masih terbuka dari SSID ujian. Perbaiki aturan router sebelum ujian. |
| Perlu Stop/Restart saat ujian | Diblokir. Hanya untuk darurat: isi alasan (min. 10 karakter); tindakan dicatat di audit. |

Klasifikasi insiden mengikuti PRD §18.3 (S1 kritis sampai S4 rendah). Untuk S1 (server/DB gagal,
semua siswa terdampak): jangan restart berulang; amankan data, cek log, hubungi penanggung jawab,
dan catat waktu kejadian. Siswa melanjutkan attempt yang sama setelah server pulih.

---

### 8.1 SOP listrik padam / server mati mendadak

Yang dijamin sistem (diuji M9-04, [bukti](evidence/M9-04_CHAOS_TEST.md)):
- Jawaban yang sudah berstatus **"Tersimpan di server"** tidak hilang, termasuk bila server mati
  mendadak di tengah penyimpanan.
- Lama server mati **otomatis ditambahkan** ke waktu siswa yang sedang ujian (DEC-03), tanpa
  memakai jatah jeda 5/10 menit siswa.
- Siswa melanjutkan **attempt yang sama**; timer tidak kembali ke awal.

Langkah operator:
1. **Saat padam:** catat jamnya. Minta pengawas menenangkan siswa: jangan menutup browser, jangan
   pindah perangkat. Jawaban yang belum sempat tersimpan di server bisa hilang dan perlu diisi ulang.
2. **Listrik kembali:** nyalakan router/AP **dulu**, lalu server. Service API, Caddy, dan
   PostgreSQL menyala sendiri (tidak perlu login atau membuka Control Center).
3. Buka **Control Center → Ringkasan**: Service **RUNNING**, Database **OK**. Bila belum, tunggu
   1–2 menit, lalu **Layanan → Start**.
4. Siswa **memuat ulang halaman** (atau login lagi di perangkat yang sama) dan melanjutkan.
   Pengawas memastikan status kembali **Aktif** di monitor.
5. Bila siswa ditolak "Akun masih aktif pada perangkat lain" karena pindah perangkat, pengawas
   memakai **Izinkan pindah perangkat / reset sesi** seperti biasa.
6. **Setelah ujian:** jalankan **Backup sekarang** dan catat kejadian di berita acara (jam padam,
   jam pulih, jumlah siswa terdampak).

Tidak dijamin: jawaban yang masih "tersimpan di perangkat" saat perangkat siswa ikut mati, dan
kerusakan disk server akibat padam (karena itu disarankan UPS dan backup harian).

## 9. Perintah terminal (cadangan)

Dari folder `services/api`:

```bash
uv run python -m app.cli status              # ringkasan kesehatan
uv run python -m app.cli backup              # backup manual (terenkripsi, diverifikasi)
uv run python -m app.cli backups             # daftar backup
uv run python -m app.cli rehearse            # uji restore backup terbaru
uv run python -m app.cli restore <JOB_ID> --into <nama_db_baru> --switch
uv run python -m app.cli preflight
uv run python -m app.cli set-retention --hour 2 --keep-daily 14 --keep-manual-days 90 --reason "..."
uv run python -m app.cli upgrade
uv run python -m app.cli create-admin <username> --name "Nama"
```

Tambahkan `--json` sebelum nama perintah untuk keluaran mesin.

## 10. Konfigurasi `.env`

| Kunci | Contoh | Fungsi |
|---|---|---|
| `LOCALCBT_DATABASE_URL` | `postgresql+psycopg://localcbt:…@127.0.0.1:5432/localcbt` | Koneksi database |
| `LOCALCBT_PUBLIC_HOST` | `cbt.sekolah.sch.id` | Alamat portal (preflight DNS/HTTPS, URL probe) |
| `LOCALCBT_ALLOWED_ORIGINS` | `["https://cbt.sekolah.sch.id"]` | Asal yang boleh mengirim data |
| `LOCALCBT_BACKUP_DIR` | `E:\LocalCBT-Backup` | Folder backup (drive terpisah) |
| `LOCALCBT_BACKUP_PASSPHRASE` | (rahasia, min. 12) | Kunci enkripsi backup |
| `LOCALCBT_EXAM_SUBNETS` | `["10.20.0.0/22"]` | Subnet SSID ujian untuk probe |
| `LOCALCBT_PG_BIN_DIR` | `C:\Program Files\PostgreSQL\16\bin` | Lokasi `pg_dump`/`pg_restore` bila tidak di PATH |
| `LOCALCBT_MEDIA_DIR` | `data/media` | Gambar soal |

Mengubah `.env` perlu **Restart** service agar berlaku.

## 11. Uji beban sebelum pilot (M9-03)

Membuktikan server dan Wi-Fi sekolah sanggup melayani ujian serentak. Lakukan di luar jam ujian,
**jangan di database asli**: script membuat 30 akun siswa uji (awalan `lt.`) dan 2 ujian.

1. **Database uji.** Tab **Backup & Restore** → pilih backup → **Restore…**, isi nama database
   `localcbt_load`, **jangan** centang *Alihkan service*. Lalu ubah sementara
   `LOCALCBT_DATABASE_URL` di `.env` ke `localcbt_load` dan **Restart** service.
2. **Seed** di server (folder `services/api`):
   ```bash
   uv run --with httpx python loadtest.py seed --confirm-db localcbt_load --base-url https://<portal>
   ```
   Data akun uji tersimpan di `.loadtest.json` (rahasia, jangan dibagikan).
3. **Jalankan** dari **laptop lain yang tersambung ke SSID ujian** (salin folder `services/api`
   beserta `.loadtest.json`, perlu `uv`; `--with httpx` karena instalasi server tanpa paket dev):
   ```bash
   uv run --with httpx python loadtest.py run
   ```
   Selama berjalan, pantau tab **Ringkasan** Control Center (CPU/RAM/disk).
4. Hasil **LULUS** bila simpan jawaban P95 ≤ 1,5 detik, API lain P95 ≤ 2 detik, 0 error, dan
   0 jawaban hilang. Simpan berkas `loadtest-report-*.json` untuk dokumentasi pilot.
5. **Kembalikan** `LOCALCBT_DATABASE_URL` ke database asli (salinan ada di `.env.bak-*`
   bila memakai restore --switch), lalu **Restart**. Database `localcbt_load` boleh dihapus.

Hasil uji di mesin pengembangan: [docs/evidence/M9-03_LOAD_TEST.md](evidence/M9-03_LOAD_TEST.md).
