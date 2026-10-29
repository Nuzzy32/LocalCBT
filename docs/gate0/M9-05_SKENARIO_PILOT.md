# M9-05 Skenario Pilot dengan Guru

**Tujuan:** menjalankan satu ujian latihan sungguhan di sekolah, dengan server, Wi-Fi, dan perangkat
milik sekolah dan siswa, lalu mencatat setiap masalah untuk M9-06 (triase dan checklist rilis).

Pilot ini juga menjadi bukti untuk hal yang belum bisa dibuktikan di mesin pengembangan: 30 siswa
serentak di perangkat keras sekolah, ponsel fisik, sertifikat HTTPS, dan Wi-Fi sekolah
(lihat bagian "Belum dibuktikan" di `docs/evidence/M9-0*.md`).

**Batas:** ujian latihan, **nilainya tidak resmi**. Tidak memakai data siswa asli (nama, NIS,
NISN) sampai pimpinan sekolah menyetujuinya.

---

## 1. Syarat sebelum pilot

| ✓ | Syarat | Bukti |
|---|---|---|
| ☐ | Izin pimpinan sekolah untuk pilot, termasuk pemakaian HP siswa | Surat/izin tertulis |
| ☐ | DISC-01 survei selesai dan operator sekolah ditunjuk | `DISC-01_SURVEI_SERVER.md` ditandatangani |
| ☐ | DISC-04 lulus untuk semua jenis perangkat yang akan dipakai siswa | `DISC-04_UJI_HTTPS.md` |
| ☐ | DISC-02 ditandatangani, **atau** guru setuju nilai pilot hanya untuk percobaan | `DISC-02_CONTOH_NILAI.md` |
| ☐ | Server terpasang dan bertahan setelah restart (ADMIN_GUIDE §2) | Portal hidup setelah reboot |
| ☐ | Uji beban 30 siswa **LULUS di server sekolah** dari laptop di SSID ujian (ADMIN_GUIDE §11) | `loadtest-report-*.json` |
| ☐ | Backup **VERIFIED** dan **Uji restore** lulus | Tabel Backup & Restore |
| ☐ | Preflight: tidak ada FAILED; `wan_blocked` OK minggu ini | Foto layar tab Jaringan |
| ☐ | Jam server tersinkron (NTP) | |

Bila uji beban di server sekolah gagal, pilot dengan 30 siswa **ditunda**. Pilot kecil (5–10 siswa)
tetap boleh untuk menguji alur.

---

## 2. Peserta dan peran

| Peran | Jumlah | Tugas di pilot |
|---|---|---|
| Operator sekolah | 1 | Server, Control Center, Wi-Fi, backup |
| Admin sekolah | 1 | Kelas, mapel, akun guru/pengawas, impor siswa pilot |
| Guru pemilik ujian | 1–2 | Bank soal, ujian, token, hasil |
| Pengawas | 1 per ruang | Memantau, menangani gangguan, berita acara |
| Siswa | 20–30 (satu kelas) | Mengerjakan ujian latihan dengan perangkat masing-masing |
| Pencatat (pengembang) | 1–2 | **Hanya mengamati dan mencatat.** Tidak membantu kecuali S1/S2, supaya terlihat bagian mana yang membingungkan. |

---

## 3. Persiapan (H-7 sampai H-1)

| Hari | Siapa | Langkah | ✓ |
|---|---|---|---|
| H-7 | Admin | Buat kelas `PILOT`, mapel, akun guru dan pengawas | ☐ |
| H-7 | Admin | Impor siswa pilot dari XLSX dengan **nama dan NIS samaran** (mis. `Peserta 01`, NIS `P001`). Cetak kartu login dari CSV kredensial. | ☐ |
| H-7 | Guru | Baca `TEACHER_QUICKSTART.md`, lalu buat bank soal **tanpa bantuan**: 15–20 soal, ketiga jenis soal, minimal satu bergambar dan satu memakai stimulus bersama. Satu soal diimpor dari template XLSX/DOCX. | ☐ |
| H-5 | Guru | Buat ujian 30–40 menit, pilih "Kapan siswa melihat nilai", aktifkan pembahasan, publikasikan, tugaskan pengawas. Buat **Batas akhir mulai** dekat dengan jam mulai (mis. 15 menit), karena pembahasan baru terbuka setelah batas akhir mulai + durasi lewat. | ☐ |
| H-3 | Pengawas | Baca `PROCTOR_SOP.md`. Coba **Pantau** dari jaringan staf | ☐ |
| H-1 | Operator | Checklist pagi hari ujian (ADMIN_GUIDE §4.3) dijalankan sehari lebih awal; satu akun siswa uji login sampai mengumpulkan | ☐ |
| H-1 | Operator | Pasang sertifikat (bila memakai strategi S1 di DISC-04) di HP siswa pilot | ☐ |
| H-1 | Pencatat | Cetak lembar §6 dan §7, siapkan jam (pakai jam server di monitor) | ☐ |

---

## 4. Hari pilot

| Waktu | Kegiatan | Yang dicatat |
|---|---|---|
| −30' | Operator: checklist pagi (ADMIN_GUIDE §4.3), Control Center **Ringkasan** tanpa merah | Foto Ringkasan |
| −15' | Pengawas: SOP §1, buka **Pantau** | Jumlah "Belum mulai" = jumlah siswa hadir |
| −10' | Pengawas membacakan aturan; siswa tersambung ke SSID ujian | Berapa siswa gagal tersambung Wi-Fi dan sebabnya |
| 0' | Siswa login, isi token, **Mulai ujian** | Waktu sampai **semua** siswa berstatus Mengerjakan; jumlah siswa yang perlu dibantu |
| 0–40' | Mengerjakan, termasuk skenario gangguan §5 | Kejadian di §6 |
| ~40' | Waktu habis / siswa mengumpulkan | Semua berstatus Selesai; ada yang tertinggal? |
| +5' | Operator: **Backup sekarang**; Log → **Ekspor…** | Backup VERIFIED, berkas log |
| +10' | Guru: **Hasil & nilai**, **Unduh XLSX**, publikasi nilai bila dipilih | Nilai muncul? XLSX terbuka? |
| +15' | Kuesioner singkat (§7) | |
| Setelah ujian usai | Siswa membuka pembahasan | Pembahasan terbuka hanya setelah ujian usai |

Selama ujian, pantau **Ringkasan** Control Center (CPU, RAM, disk) dan foto layarnya di menit ke-5,
ke-20, dan menjelang selesai.

---

## 5. Skenario gangguan yang disengaja

Dilakukan oleh 1–3 siswa yang sudah diberi tahu sebelumnya, di menit yang sudah ditentukan.
Tujuannya membuktikan alur pemulihan di perangkat dan Wi-Fi asli, bukan menguji siswa.

| No | Menit | Skenario | Yang diharapkan | Hasil | ✓ |
|---|---|---|---|---|---|
| G1 | 10' | Siswa A mematikan Wi-Fi 1 menit, menjawab 1 soal, lalu menyalakan lagi | Layar: "Koneksi ke server terputus", waktu dijeda; monitor: **Dijeda**. Setelah tersambung, jawaban menjadi "Tersimpan di server" dan batas waktu siswa mundur kira-kira 45 detik (1 menit dikurangi 15 detik deteksi, SOP §3) | | ☐ |
| G2 | 15' | Siswa B memuat ulang halaman (refresh / tarik ke bawah) | Kembali ke soal yang sama, jawaban dan sisa waktu utuh | | ☐ |
| G2b | 17' | Siswa B menutup browser sepenuhnya, lalu membuka portal lagi di perangkat yang sama | Bila browser masih ingat sesi: langsung lanjut. Bila diminta login lalu ditolak "Akun masih aktif pada perangkat lain": pengawas memakai **Izinkan pindah perangkat / reset sesi**. **Catat browser mana yang mana**: bahan SOP pengawas. | | ☐ |
| G3 | 20' | Siswa C pindah ke perangkat lain | Ditolak "Akun masih aktif pada perangkat lain"; pengawas memakai **Izinkan pindah perangkat / reset sesi** (SOP §5); lanjut di perangkat baru | | ☐ |
| G4 | 25' | Pengawas menambah waktu satu siswa dan mengirim pengumuman | Sisa waktu siswa itu bertambah; pengumuman tampil di semua layar | | ☐ |
| G5 | 30' | Siswa D pindah ke aplikasi lain 30 detik lalu kembali | Monitor menandai pindah tab; pengawas mengecek langsung (bukan bukti curang) | | ☐ |
| G6 | Opsional, hanya bila disetujui operator | Satu AP dimatikan 2 menit | Siswa di AP itu Dijeda lalu pulih; tidak ada jawaban "Tersimpan di server" yang hilang | | ☐ |

**Jangan** mematikan server, PostgreSQL, atau listrik saat pilot. Skenario itu sudah diuji otomatis
di M9-04 dan tidak perlu dibebankan ke siswa.

---

## 6. Catatan kejadian

Tingkat mengikuti PROCTOR_SOP §9: **S1** kritis (semua siswa terdampak), **S2** tinggi (sebagian
siswa tidak bisa menyimpan), **S3** sedang (satu siswa), **S4** rendah (tampilan, tidak mengganggu).

| No | Jam (server) | Peran | Perangkat / browser | Kejadian (apa yang dilihat) | Dampak (berapa siswa, jawaban hilang?) | Tingkat | Tindakan saat itu |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |
| 6 | | | | | | | |
| 7 | | | | | | | |
| 8 | | | | | | | |

Catat juga hal yang membingungkan walau tidak error: tombol yang dicari lama, pesan yang tidak
dipahami, pertanyaan yang sama dari banyak siswa.

---

## 7. Kuesioner singkat

Skala 1 (sangat sulit / sangat tidak setuju) sampai 5 (sangat mudah / sangat setuju).

**Guru**

| Pertanyaan | 1–5 / jawaban |
|---|---|
| Membuat soal dan ujian tanpa bantuan | |
| Memahami status di halaman hasil | |
| Nilai di XLSX sesuai hitungan Anda (cek 3 siswa dengan tangan, pakai aturan DISC-02) | ☐ Sesuai ☐ Tidak |
| Bagian yang paling membingungkan | |
| Bersedia memakai untuk ulangan berikutnya? Syaratnya? | |

**Pengawas**

| Pertanyaan | 1–5 / jawaban |
|---|---|
| Membaca layar monitor | |
| Menangani siswa terputus / pindah perangkat | |
| SOP cukup jelas? Bagian mana yang kurang? | |

**Siswa** (cukup lisan atau angkat tangan; catat jumlahnya)

| Pertanyaan | Jumlah |
|---|---|
| Login dan masuk ujian mudah | |
| Teks dan tombol terbaca jelas di HP | |
| Pernah ragu apakah jawaban sudah tersimpan | |
| Ada soal/gambar yang terpotong | |

---

## 8. Kriteria selesai pilot (lanjut ke M9-06)

| ✓ | Kriteria |
|---|---|
| ☐ | **0 jawaban hilang**: setiap jawaban yang pernah "Tersimpan di server" ada di hasil |
| ☐ | Semua siswa berstatus Selesai dan dinilai |
| ☐ | Nilai 3 siswa yang dihitung tangan oleh guru sama dengan XLSX |
| ☐ | Tidak ada kejadian S1 atau S2 yang penyebabnya belum diketahui |
| ☐ | Skenario G1–G5 berhasil sesuai yang diharapkan (G2b: perilaku tiap browser tercatat) |
| ☐ | Backup setelah ujian VERIFIED |
| ☐ | Catatan kejadian, kuesioner, foto Ringkasan, ekspor log, dan laporan uji beban dikumpulkan ke `docs/evidence/M9-05_PILOT.md` (tanpa nama siswa) |

Keputusan setelah pilot:

☐ Lanjut ke M9-06 ☐ Perbaiki lalu pilot ulang ☐ Tunda, alasan: ______________________

Data pilot (akun dan nilai samaran) setelah selesai: ☐ disimpan ☐ dihapus, oleh: ______________

| | Nama | Tanda tangan | Tanggal |
|---|---|---|---|
| Guru | | | |
| Operator sekolah | | | |
| Pimpinan sekolah | | | |
| Pengembang | | | |
