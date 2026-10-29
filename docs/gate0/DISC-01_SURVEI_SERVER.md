# DISC-01 Survei Server, Jaringan & Perangkat Sekolah

**Tujuan:** mencatat inventaris yang benar-benar ada di sekolah, bukan perkiraan. Hasilnya dipakai
untuk memilih komputer server, menyusun aturan router, dan menentukan kapan uji beban 30 siswa
(ADMIN_GUIDE §11) dijalankan di perangkat keras sekolah.

**Lulus bila:** semua bagian terisi (boleh "tidak ada" / "tidak tahu", jangan dikosongkan) dan
ada **operator sekolah** yang ditunjuk dan menandatangani.

Menjawab: OQ-02 (perangkat peserta), OQ-03 (server, router, AP, UPS), DEC-07 (spesifikasi minimal).

| Sekolah | | Tanggal survei | |
|---|---|---|---|
| Pengisi | | Didampingi | |

---

## A. Penanggung jawab

| Peran | Nama | Kontak (HP/WA) |
|---|---|---|
| Operator LocalCBT (merawat server, backup) | | |
| Admin LocalCBT (akun, kelas, siswa) | | |
| Pengelola jaringan / router | | |
| Pimpinan yang menyetujui (Kepsek/Wakasek) | | |

Siapa yang memegang kata sandi admin router? ______________________

## B. Skala ujian

| Pertanyaan | Jawaban |
|---|---|
| Jumlah kelas / rombel yang akan memakai LocalCBT | |
| Jumlah siswa total | |
| Jumlah siswa per kelas (paling banyak) | |
| **Siswa ujian bersamaan pada jam sibuk** (semua ruang dijumlah) | |
| Jumlah ruang ujian bersamaan | |
| Jumlah guru yang membuat soal | |
| Jumlah pengawas per sesi | |
| Jenis ujian pertama yang direncanakan (ulangan harian, PTS, PAS, try out) | |
| Perkiraan tanggal ujian pertama | |

> Uji beban baru membuktikan **30 siswa serentak**. Bila jam sibuk lebih dari 30, perlu uji beban
> tambahan sebelum dipakai (NFR-15).

## C. Komputer calon server

Cara cepat membaca spesifikasi:
- **Windows:** tekan Win+R, ketik `msinfo32`, lalu foto halaman *System Summary*. Kapasitas disk
  dilihat di *This PC*.
- **macOS:** menu Apple → *About This Mac* → *More Info*, lalu foto layarnya.

| Pertanyaan | Jawaban |
|---|---|
| Merek / model | |
| Sistem operasi & versi (mis. Windows 11 Pro 23H2, macOS 15.3) | |
| Prosesor (CPU) & jumlah core | |
| RAM | |
| Disk utama: jenis (SSD/HDD), kapasitas, sisa kosong | |
| Disk kedua / eksternal untuk backup (ada? kapasitas?) | |
| Umur komputer (tahun) | |
| Dipakai untuk keperluan lain? (Dapodik, TU, lab, dll.) | |
| Kami punya akun **administrator** di komputer ini? | ☐ Ya ☐ Tidak |
| Antivirus / pengaman yang terpasang | |
| Komputer boleh menyala terus selama musim ujian? | ☐ Ya ☐ Tidak |
| Tersambung ke router lewat **kabel LAN**? | ☐ Kabel ☐ Wi-Fi |
| Jam komputer tersinkron otomatis (NTP)? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Ada komputer cadangan bila server rusak? | |

## D. Listrik

| Pertanyaan | Jawaban |
|---|---|
| UPS untuk server? Merek/kapasitas, kira-kira tahan berapa menit? | |
| UPS untuk router & access point? | |
| Seberapa sering listrik padam di sekolah? | |
| Ada genset? | |
| Colokan untuk mengisi daya HP siswa di ruang ujian? | |

## E. Jaringan

| Pertanyaan | Jawaban |
|---|---|
| Router utama: merek & model | |
| Access point (AP): merek, model, jumlah, letak (ruang mana) | |
| Berapa perangkat maksimal per AP menurut spesifikasinya? | |
| Router/AP bisa membuat **SSID terpisah** untuk ujian dan staf? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Bisa **VLAN**? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Bisa memblokir internet untuk satu SSID/VLAN saja? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Firewall bisa mengatur **IPv6** juga? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Ada *client isolation* (perangkat siswa tidak saling melihat)? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Server bisa diberi IP tetap (DHCP reservation / statis)? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Ada **DNS lokal** (router bisa menambah nama → IP)? | ☐ Ya ☐ Tidak ☐ Tidak tahu |
| Rentang IP jaringan sekarang (mis. 192.168.1.0/24) | |
| Penyedia internet (ISP) & apakah IPv6 aktif | |
| Wi-Fi sering lambat/putus di ruang tertentu? Ruang mana? | |

Gambarkan denah singkat: letak server, router, AP, dan ruang ujian.

&nbsp;

&nbsp;

&nbsp;

## F. Perangkat peserta

| Pertanyaan | Jawaban |
|---|---|
| Siswa ujian memakai: ☐ HP pribadi ☐ laptop pribadi ☐ komputer lab ☐ campuran | |
| Perkiraan % Android / iPhone / laptop | |
| Versi Android/iOS tertua yang masih dipakai siswa (tanyakan beberapa siswa) | |
| Browser yang biasa dipakai (Chrome, Samsung Internet, Safari, lainnya) | |
| Komputer lab: jumlah, OS, browser | |
| Perangkat cadangan untuk siswa yang HP-nya rusak/habis baterai | |
| Siswa boleh memasang sertifikat/profil di HP pribadinya? (lihat DISC-04) | ☐ Ya ☐ Tidak ☐ Perlu izin |

## G. Domain & sertifikat (bahan DISC-04)

| Pertanyaan | Jawaban |
|---|---|
| Sekolah punya domain sendiri? (mis. `sekolah.sch.id`) | |
| Siapa yang bisa mengubah DNS domain itu (dinas, vendor web, sekolah)? | |
| Boleh dibuat subdomain untuk ujian (mis. `cbt.sekolah.sch.id`)? | ☐ Ya ☐ Tidak ☐ Perlu izin |

## H. Catatan

&nbsp;

&nbsp;

---

| | Nama | Tanda tangan | Tanggal |
|---|---|---|---|
| Operator sekolah | | | |
| Pimpinan sekolah | | | |
| Pengembang | | | |
