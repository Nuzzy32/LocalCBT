# M9-04 Uji Gangguan

**Tanggal:** 21 Oktober 2026 · **Status:** semua skenario otomatis LULUS di mesin pengembangan
dan dijalankan ulang di CI tiap push. Skenario fisik (Wi-Fi sekolah, listrik padam) belum diuji
di lokasi.

## Hasil

| Skenario (DEVELOPMENT_PLAN M9-04) | Cara uji | Hasil |
|---|---|---|
| Browser refresh | `chaos.py refresh`: muat ulang halaman + masuk ulang alur Mulai | **LULUS**: attempt yang sama, jawaban utuh, timer berjalan terus (1800 → 1798 dtk), tidak ter-reset |
| Wi-Fi putus | `chaos.py wifi_drop`: siswa diam 25 dtk | **LULUS**: monitor pengawas menampilkan PAUSED; kredit jeda 10 dtk = geser deadline 10 dtk (jeda mulai 15 dtk setelah heartbeat terakhir) |
| Server dimatikan paksa | `chaos.py server_kill`: `kill -9` saat 4 siswa menyimpan, mati 21 dtk | **LULUS**: 164 retry klien, semua 40 jawaban ber-ACK selamat, tidak ada revisi ganda; outage 21 dtk dikompensasi ke deadline tanpa memakai jatah jeda siswa (DEC-03) |
| DB restart | `chaos.py db_restart`: restart PostgreSQL saat siswa menyimpan | **LULUS**: health melapor DOWN (T-017), API pulih 1 dtk setelah DB kembali, 0 jawaban ber-ACK hilang |
| Submit setelah gangguan | `chaos.py submit` | **LULUS**: 1 receipt per siswa walau dikirim ganda |
| Disk penuh saat backup | `test_disk_full_during_backup_fails_loudly_and_cleans_up` (ENOSPC disimulasikan) | **LULUS**: status FAILED dengan alasan, tidak ada folder parsial/data terdekripsi tersisa, tampil di Control Center |
| Listrik padam | SOP manual | [ADMIN_GUIDE §8.1](../ADMIN_GUIDE.md#81-sop-listrik-padam--server-mati-mendadak); perilaku server mati mendadak dibuktikan oleh `server_kill` |

Aturan jeda 5/10 menit dengan durasi penuh (TC-08 putus 7 menit, TC-09 putus 3×4 menit) diuji
dengan manipulasi waktu di `tests/test_pause.py`. Di sini diuji integrasinya secara nyata
(sweeper, monitor, heartbeat).

## Temuan

1. **Jam database bisa berbeda dari jam server aplikasi (diperbaiki, deteksi).** Selama uji, jam
   VM Docker tertinggal 4,5 menit dari jam host. Akibatnya ujian yang baru dibuat dianggap "belum
   dibuka", karena jendela mulai dihitung dari satu jam dan dicek dengan jam lain. Di sekolah hal
   serupa terjadi bila PostgreSQL berjalan di VM/mesin lain atau jam tidak tersinkron.
   Perbaikan:
   - preflight **clock** sekarang membandingkan jam DB dengan jam proses API (gagal bila selisih
     lebih dari 5 dtk);
   - seed uji beban memakai jam DB.

   Sinkronisasi NTP tetap dicek operator (status WARNING, bukan OK).
2. Tidak ditemukan kehilangan data atau kemacetan pada kill -9 maupun restart DB.
   `pool_pre_ping` dan retry klien dengan Idempotency-Key yang sama bekerja seperti dirancang.

## Belum dibuktikan

- **Antrean offline di browser** (jawaban "tersimpan di perangkat" lalu tersinkron) dan tampilan
  status offline. Ini sisi UI, jadi masuk regresi browser M9-01 (Playwright).
- **Wi-Fi/AP sekolah sungguhan**: roaming antar-AP, jitter, captive portal; interval heartbeat
  belum dikalibrasi di lapangan (OQ-05, ADR-004).
- **Listrik padam sungguhan**: urutan menyala router → server, autostart service di Windows
  (WinSW belum diuji di mesin Windows asli), dan kerusakan disk.
- **Disk database penuh**: tidak aman disimulasikan di mesin bersama. Pencegahannya lewat
  peringatan disk WARNING/CRITICAL di Control Center.

## Menjalankan ulang

```bash
cd services/api
createdb localcbt_chaos   # atau via psql: create database localcbt_chaos
LOCALCBT_DATABASE_URL=postgresql+psycopg://…/localcbt_chaos uv run alembic upgrade head
LOCALCBT_DATABASE_URL=postgresql+psycopg://…/localcbt_chaos uv run python chaos.py \
  --confirm-db localcbt_chaos --db-restart-cmd "docker compose -f ../../compose.dev.yml restart db"
```

Di server sekolah, `--db-restart-cmd` diisi perintah restart service PostgreSQL. Contoh macOS
Homebrew: `brew services restart postgresql@16`; Windows: `sc stop postgresql-x64-16` lalu start.
Selalu pakai database uji, jangan database asli.
