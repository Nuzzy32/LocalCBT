# M9-03 Uji Beban: 30 siswa, 2 ujian

**Tanggal:** 21 Oktober 2026 · **Commit:** M9-03 (setelah `ef43d9c`) · **Status:** LULUS di mesin
pengembangan; **belum** diulang di server dan jaringan sekolah.

## Ringkasan

| Skenario | Hasil |
|---|---|
| 30 siswa, 2 ujian, jeda jawab ±2 dtk (skenario PRD) | **LULUS** — simpan jawaban P95 **27 ms** (target ≤ 1.500 ms), semua API P95 ≤ 660 ms (target ≤ 2.000 ms), 0 error, 0 jawaban hilang |
| 30 siswa, jeda jawab ±0,2 dtk (agresif) | **LULUS** — simpan jawaban P95 13 ms, 0 error |
| 120 siswa serentak (4× target, uji tekanan) | Tanpa error & tanpa jawaban hilang; **login P95 2,5 dtk** saat 120 login ditembak pada milidetik yang sama (di atas target 2 dtk) |

Dua cacat ditemukan dan diperbaiki dalam milestone ini (lihat Temuan). Sebelum perbaikan,
**120 login serentak membuat seluruh API macet** sampai timeout.

## Metode

- Script: [`services/api/loadtest.py`](../../services/api/loadtest.py), juga dijalankan di CI tiap push
  (30 siswa, 20 soal, jeda 0,5 dtk; laporan JSON jadi artifact).
- Data: 30 siswa dibagi 2 kelas, 2 ujian berbeda dengan 40 soal yang sama (PG, PG kompleks,
  Benar/Salah bergantian), durasi 90 menit, 1 guru, 1 pengawas.
- Perilaku tiap siswa virtual:
  1. login dan membuka daftar ujian;
  2. **serentak** memasukkan token dan menekan Mulai;
  3. menjawab 40 soal dengan jeda acak, lalu mengubah ±20% jawaban;
  4. heartbeat tiap 5 detik seperti browser;
  5. memverifikasi bahwa setiap jawaban yang mendapat ACK server benar-benar tersimpan;
  6. **serentak** mengumpulkan, dengan klik ganda memakai kunci idempotensi yang sama.
- Bersamaan: pengawas memantau kedua ujian lewat WebSocket, dan guru mengekspor nilai XLSX tiap 20 detik.
- Server: uvicorn 1 proses dengan argumen sama seperti service produksi, sweeper aktif, scheduler
  backup mati. Database: PostgreSQL 16 (Docker).
- Mesin: Apple M5, 16 GB RAM. Generator beban berjalan di mesin yang sama dengan server, jadi ikut
  memakan CPU.

### Hasil rinci: 30 siswa, jeda ±2 dtk

| Endpoint | n | Error | P50 ms | P95 ms | P99 ms | Max ms | Target P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| login | 30 | 0 | 551 | 659 | 660 | 660 | 2.000 |
| list_exams | 30 | 0 | 101 | 166 | 305 | 346 | 2.000 |
| verify_token | 30 | 0 | 486 | 542 | 558 | 565 | 2.000 |
| start_attempt | 30 | 0 | 114 | 266 | 268 | 269 | 2.000 |
| save_answer | 1.440 | 0 | 18 | **27** | 37 | 108 | **1.500** |
| heartbeat | 660 | 0 | 18 | 55 | 68 | 76 | 2.000 |
| get_attempt | 30 | 0 | 16 | 22 | 22 | 22 | 2.000 |
| submit (2× per siswa) | 60 | 0 | 111 | 246 | 254 | 256 | 2.000 |
| export_xlsx (saat ujian) | 12 | 0 | 26 | 246 | 388 | 424 | 2.000 |

Monitor pengawas: 74 snapshot, jeda terlama 3,03 detik (interval 3 detik). Integritas: semua 1.440
jawaban ber-ACK cocok dengan server; 30 siswa = 30 attempt = 30 receipt tunggal.

Login dan token lebih lambat karena keduanya memverifikasi hash Argon2 (sengaja mahal untuk
melawan tebak sandi) dan 30 siswa menekannya pada saat yang sama.

## Temuan dan perbaikan

1. **API macet saat lonjakan request (kritis, diperbaiki).** FastAPI mengambil koneksi DB
   (`get_db`) di satu giliran thread dan menjalankan handler di giliran berikutnya. Bila jumlah
   request serentak melebihi pool + thread, semua koneksi dipegang request yang menunggu thread,
   sementara semua thread menunggu koneksi, sehingga semua request macet 30 detik lalu gagal 500.
   Dengan 120 login serentak, **120/120 gagal**.
   Perbaikan: request HTTP yang diproses bersamaan dibatasi 24 (`MAX_INFLIGHT`, `app/main.py`);
   sisanya mengantre murah di event loop. Pool DB disamakan dengan thread AnyIO (10 + 30 = 40).
   Tes `test_inflight_limit_leaves_headroom_against_pool_thread_deadlock` menjaga invariannya.
2. **Submit serentak bisa gagal di koneksi basi (sedang, diperbaiki).** uvicorn menutup koneksi
   keep-alive yang menganggur setelah 5 detik. Di run pertama 5 dari 60 submit gagal `ReadError`.
   Di produksi, kasus yang sama terjadi antara Caddy dan uvicorn dan muncul ke siswa sebagai 502.
   Perbaikan: Caddy `keepalive 30s` < uvicorn `--timeout-keep-alive 75` (Caddyfile, launchd,
   WinSW). Setelah itu 0 error.
3. **Memori Argon2 tidak dibatasi (sedang, diperbaiki).** Setiap hash memakai 64 MiB. Dengan 40
   thread, login serentak bisa memakan sekitar 2,5 GB RAM sekaligus. Perbaikan: hash/verifikasi
   dibatasi sejumlah core CPU (`_hash_slots`, `app/auth.py`).

## Batasan & yang belum dibuktikan

- **Belum diuji di perangkat keras sekolah** (DEC-07, OQ-03) maupun lewat Wi-Fi/AP sekolah
  (jitter, roaming). Angka di atas adalah batas bawah dari mesin cepat dengan jaringan loopback.
- Caddy/TLS belum ada di jalur uji lokal. Run di sekolah harus lewat `https://<portal>` dari
  laptop lain di SSID ujian.
- Generator beban satu mesin dengan server: CPU berbagi.
- Hasil tidak boleh diklaim untuk lebih dari 30 peserta (NFR-15) sebelum diulang di server sekolah;
  uji 120 siswa hanya menunjukkan ada cadangan kapasitas dan tidak ada kemacetan.
- Backup otomatis tidak berjalan selama uji. Skenario "backup paksa saat ujian" belum diukur.

## Mengulang di sekolah

Lihat [ADMIN_GUIDE §11](../ADMIN_GUIDE.md#11-uji-beban-sebelum-pilot-m9-03). Ringkasnya: restore
backup ke database uji, arahkan service ke sana, seed, jalankan `run` dari laptop di SSID ujian,
simpan JSON laporan di folder ini, lalu kembalikan service ke database asli.
