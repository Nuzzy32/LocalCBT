# SOP Pengawas Ujian — LocalCBT

Prosedur ini untuk pengawas (guru pemilik ujian atau pengawas yang ditugaskan).
Pegang dokumen ini selama ujian. Nama tombol dan status sama dengan yang tampil di layar.

Prinsip utama:
- **Server yang menentukan waktu.** Jam di HP/laptop siswa tidak dipakai.
- **Jawaban aman hanya bila "Tersimpan di server".** Jawaban yang masih "tersimpan di
  perangkat" belum dihitung.
- **Pindah tab bukan bukti curang.** Itu hanya tanda untuk dicek langsung.
- Pengawas **tidak bisa** melihat kunci, nilai, atau jawaban siswa, dan **tidak bisa**
  membuka lagi ujian siswa yang sudah dikumpulkan.

---

## 1. Sebelum ujian (H-1 sampai 15 menit sebelum mulai)

| ✓ | Langkah |
|---|---|
| ☐ | Pastikan Anda sudah ditugaskan. Masuk ke portal dari **jaringan staf**. Akun pengawas langsung masuk ke halaman **Pengawasan**; akun guru membuka tab **Pengawasan** di menu guru (atau tombol **Pantau** untuk ujian sendiri). Ujian harus muncul di daftar. |
| ☐ | Minta **token ujian** kepada guru pemilik. Token tidak bisa dilihat di layar pengawas dan tidak ditampilkan ulang. |
| ☐ | Catat jadwal: **Mulai dibuka**, **Batas akhir mulai**, dan durasi. Siswa tidak bisa mulai di luar rentang ini, dan rentang tidak bisa diperpanjang setelah publish. |
| ☐ | Tekan **Pantau**. Pastikan jumlah **Belum mulai** sama dengan jumlah siswa di daftar hadir. |
| ☐ | Pastikan teks "Diperbarui HH:MM (waktu server)" berganti tiap beberapa detik. |
| ☐ | Pastikan siswa tersambung ke **Wi-Fi ujian** dan bisa membuka halaman login. |
| ☐ | Simpan nomor/kontak **operator** dan **admin** sekolah. |
| ☐ | Siapkan lembar berita acara (nama, NIS, jam kejadian, tindakan, alasan). |
| ☐ | Bacakan aturan kepada siswa: jangan menutup halaman, perhatikan tanda "Tersimpan di server", lapor bila ada masalah perangkat/jaringan. |

Alur siswa (agar Anda bisa membantu):
1. Login **NIS / Username** + **Kata sandi**.
2. Pilih ujian, isi **Token ujian dari pengawas**, tekan **Lanjut**.
3. Baca **Sebelum mulai**, centang **Saya sudah membaca petunjuk dan siap mengerjakan**,
   tekan **Mulai ujian** dalam **5 menit**. Lewat 5 menit, siswa diminta memasukkan token lagi.
4. Waktu siswa mulai berjalan sejak **Mulai ujian** ditekan.

---

## 2. Membaca layar monitor

Monitor diperbarui otomatis sekitar tiap 3 detik. Klik kotak ringkasan di atas untuk
menyaring. Kolom **Cari peserta** menerima nama atau NIS. Menu **Tampilkan** punya pilihan
**Perlu ditinjau** untuk siswa yang tercatat pindah tab.

| Status | Arti | Waktu siswa | Tindakan |
|---|---|---|---|
| ○ Belum mulai | Belum menekan Mulai | Belum berjalan | Pastikan siswa hadir dan punya token |
| ● Aktif | Tersambung dan mengerjakan | Berjalan | Tidak perlu tindakan |
| ⚠ Terputus | Tidak ada sinyal dari perangkat >15 detik, **dan tidak sedang dijeda** (bisa tampil beberapa detik sebelum berubah jadi Dijeda; bila menetap, jatah jeda sudah habis) | **Tetap berjalan** | **Segera tangani** (lihat 4) |
| ⏸ Dijeda | Koneksi terputus, jeda otomatis aktif | **Dibekukan** | Bantu siswa tersambung lagi |
| ✓ Selesai | Sudah dikumpulkan (oleh siswa atau otomatis saat waktu habis) | — | Tidak ada tindakan |

Kolom tabel: **NIS**, **Peserta**, **Terjawab** (jumlah dijawab/total soal), **Status**,
**Sisa** (menit:detik), **Aksi**. Tombol aksi **Tangani** muncul untuk Terputus/Dijeda,
**Detail** untuk lainnya.

Tanda tambahan di nama siswa:
- **Perlu ditinjau (n)**: siswa pindah tab/aplikasi sebanyak n kali.
- **Izin pindah perangkat**: izin pindah perangkat sedang aktif.

Bila muncul **"Data monitoring mungkin terlambat."**, tekan **Sinkronkan**. Bila tetap
muncul lebih dari 1 menit, hubungi operator (lihat 9).

---

## 3. Jeda otomatis (auto-pause)

Aturan di server:

| Aturan | Nilai |
|---|---|
| Siswa dianggap putus setelah tanpa sinyal | **15 detik** |
| Jeda maksimal per gangguan | **5 menit** |
| Total jeda per siswa per ujian | **10 menit** |
| Jatah total di-reset saat login ulang/ganti perangkat? | **Tidak** |

Cara kerjanya:
1. Perangkat siswa mengirim sinyal tiap beberapa detik. Bila 15 detik tidak ada sinyal,
   status menjadi **Dijeda** dan waktu siswa dibekukan.
2. Saat siswa tersambung lagi, jeda berakhir otomatis. Waktu yang dibekukan ditambahkan
   ke batas waktu siswa.
3. Bila putusnya lebih dari 5 menit, jeda berhenti sendiri. Waktu siswa **kembali berjalan**
   dan status menjadi **Terputus**. Gangguan yang sama tidak memberi jeda baru.
4. Bila total jeda sudah 10 menit, gangguan berikutnya **tidak dijeda lagi**.
5. 15 detik pertama sebelum terdeteksi tidak dikembalikan.

Di layar **Tangani/Detail** tertulis "jeda terpakai m:ss dari 10:00".

Di layar siswa muncul: "Koneksi ke server terputus. Jawaban baru tersimpan di perangkat dan
belum dikirim." disertai "Waktu ujian dijeda sementara." atau, bila jatah habis,
"Batas jeda telah tercapai. Waktu ujian kembali berjalan. Hubungi pengawas."

---

## 4. Menangani siswa terputus

1. Tekan **Tangani** pada baris siswa. Lihat **Riwayat** (jeda koneksi, pindah tab, tambah
   waktu, izin pindah perangkat).
2. Datangi siswa. Periksa: Wi-Fi ujian tersambung? Mode pesawat? Baterai?
3. Minta siswa **memuat ulang halaman** (jangan menutup browser). Siswa kembali ke ujian
   yang sama; jawaban yang sudah tersimpan di server tetap ada.
4. Pastikan status kembali **Aktif** dan tanda di layar siswa berubah menjadi
   "Tersimpan di server pukul …".
5. Bila status **Terputus** (jeda sudah habis, waktu berjalan) dan gangguan bukan kesalahan
   siswa, pertimbangkan **tambah waktu** (lihat 6) **sebelum waktunya habis**.
6. Bila perangkat rusak, lakukan **pindah perangkat** (lihat 5).
7. Catat di berita acara.

Bila banyak siswa terputus **bersamaan**, kemungkinan masalah jaringan/server: lihat 8 dan 9.

---

## 5. Pindah perangkat / reset sesi

Satu akun siswa hanya boleh aktif di satu perangkat. Bila siswa login di perangkat lain,
ia mendapat pesan "Akun masih aktif pada perangkat lain. Hubungi pengawas untuk pindah
perangkat."

Selama ujian siswa masih berjalan, pesan ini **tidak hilang dengan sendirinya**, meskipun
perangkat lama sudah lama mati atau ditinggal: pindah perangkat **selalu** lewat pengawas.

Langkah:
1. Pastikan siswa yang meminta memang pemilik akun (cek wajah/kartu).
2. Tekan **Tangani** atau **Detail** pada siswa itu.
3. Isi **Alasan tindakan (wajib, min. 10 karakter)**, contoh: "HP mati, pindah ke laptop lab 3".
4. Tekan **Izinkan pindah perangkat / reset sesi**.
5. Muncul "Izin pindah perangkat aktif 5 menit. Minta siswa login di perangkat baru."
6. Minta siswa login di perangkat baru **dalam 5 menit**. Bila login masih ditolak, ulangi
   langkah 2–4.

Yang perlu diketahui:
- Tombol ini dipakai untuk **pindah perangkat** maupun **reset sesi**; keduanya sama.
- Perangkat lama **langsung keluar saat tombol ditekan**. Perangkat yang lebih dulu login
  sesudahnya yang dipakai; perangkat lain yang mencoba login lagi akan ditolak.
- Ujian, jawaban yang sudah di server, sisa waktu, dan jatah jeda **tidak berubah**.
- Jawaban yang masih "tersimpan di perangkat" pada perangkat lama **tidak ikut pindah**.
  Bila perangkat lama masih bisa menyala, sambungkan dulu agar jawabannya terkirim
  **sebelum** menekan tombol; setelah tombol ditekan perangkat lama tidak bisa mengirim lagi.
- Tindakan ini tercatat (siapa, kapan, alasan) dan bisa ditinjau admin di **Riwayat
  intervensi**.
- Tidak bisa dilakukan untuk siswa yang sudah **Selesai**.

---

## 6. Menambah waktu

Gunakan hanya untuk gangguan yang bukan kesalahan siswa (perangkat rusak, listrik, jaringan
sekolah), sesuai aturan sekolah.

1. Tekan **Tangani**/**Detail** pada siswa.
2. Isi **Alasan tindakan** (min. 10 karakter), contoh: "Wi-Fi lab putus 6 menit, jeda habis".
3. Isi **Tambah waktu (menit)**: 1 sampai 120 menit sekali tambah.
4. Tekan **Tambah waktu**. Muncul "Waktu ditambahkan."

Catatan:
- Setiap penambahan tercatat (siapa, kapan, berapa, alasan) dan tampil di **Riwayat**.
- Waktu **tidak bisa** ditambah setelah siswa selesai atau waktunya sudah habis
  ("Ujian peserta ini sudah selesai."). Tambahkan **sebelum** waktu habis.
- Pengawas tidak bisa mengubah kunci, bobot, jawaban, atau nilai.

---

## 7. Pengumuman

1. Di bagian **Pengumuman**, tulis **Pesan untuk semua peserta** (maks. 500 karakter).
2. Tekan **Kirim pengumuman**, lalu konfirmasi.
3. Siswa melihatnya di atas soal: "Pengumuman HH:MM: …". Siswa yang tersambung ulang tetap
   menerimanya.
4. Di monitor, daftar pengumuman menampilkan jam, **nama pengirim**, dan isi pesan. Setiap
   pengumuman juga tercatat di log audit.

Catatan:
- Pesan terkirim ke **semua peserta ujian ini** (belum bisa per ruang/siswa).
- Pesan **tidak bisa ditarik atau diedit**. Periksa sebelum mengirim.
- Jangan menulis kunci jawaban, nilai, atau data pribadi siswa.

---

## 8. Situasi khusus

### 8.1 Pindah tab / aplikasi
- Tercatat setiap kali halaman ujian disembunyikan (pindah tab, buka aplikasi lain,
  layar HP terkunci).
- Ini **indikator, bukan bukti kecurangan**. Notifikasi HP atau layar mati juga bisa memicu.
- Tindakan: amati siswa langsung, tanyakan dengan sopan, catat di berita acara bila perlu.
  **Jangan** menghukum hanya berdasarkan angka ini.

### 8.2 Jawaban offline setelah waktu habis
- Saat offline, jawaban baru disimpan di perangkat siswa ("N jawaban tersimpan di perangkat,
  belum tersinkron").
- Bila waktu habis sebelum jawaban itu terkirim, server **menolak** jawaban tersebut.
  Siswa melihat: "N jawaban belum terkirim ke server sebelum waktu habis sehingga tidak
  dinilai. Segera hubungi pengawas."
- Pengawas **tidak bisa** memasukkan jawaban itu ke sistem dan tidak bisa membuka ulang ujian.
- Tindakan: catat NIS, jam, dan jumlah jawaban di berita acara. Laporkan ke guru pemilik
  dan admin. Keputusan mengikuti kebijakan sekolah.
- Pencegahan: siswa yang offline mendekati akhir waktu → tambah waktu **sebelum** habis.

### 8.3 Server mati / gangguan massal
- Bila server/database berhenti lebih dari ~15 detik, saat server hidup lagi **lama mati
  itu otomatis ditambahkan** ke batas waktu semua siswa yang sedang mengerjakan atau dijeda.
  Tambahan ini **tidak memakai** jatah jeda 10 menit siswa.
- Tidak ada pengumpulan otomatis massal karena server mati.
- Yang dilakukan pengawas:
  1. Minta siswa **tidak menutup** halaman ujian. Jawaban baru disimpan di perangkat.
  2. Hubungi operator segera (S1).
  3. Setelah server hidup, minta siswa memuat ulang halaman. Siswa yang belum menekan
     **Mulai ujian** mungkin diminta **memasukkan token lagi**.
  4. Monitor tersambung ulang sendiri. Tekan **Sinkronkan** bila perlu.
  5. Pastikan semua siswa kembali **Aktif** dan "Tersimpan di server".

### 8.4 Siswa lupa kata sandi
- Pengawas **tidak bisa** mengganti kata sandi.
- Hubungi **admin**. Admin memakai **Reset kata sandi siswa** di halaman Administrasi
  (isi NIS dan alasan), lalu memberikan kata sandi sementara kepada siswa. Reset juga
  mengeluarkan siswa dari semua perangkat dan tercatat di **Riwayat intervensi**.
- Selama menunggu, waktu siswa yang **belum mulai** tidak berjalan.

### 8.5 Pesan lain di layar siswa

| Pesan | Arti | Tindakan |
|---|---|---|
| "Token tidak sesuai. Tanyakan token kepada pengawas." | Token salah | Berikan token yang benar |
| "Terlalu banyak percobaan token. Hubungi pengawas." | 5 kali salah dalam 5 menit | Tunggu sampai 5 menit, lalu beri token yang benar |
| "Masukkan token ujian lagi." | Lewat 5 menit setelah token, atau server sempat restart | Isi token lagi |
| "Ujian belum tersedia atau periode mulai sudah berakhir." | Di luar rentang mulai | Lapor guru pemilik; rentang tidak bisa diubah |
| "Terlalu banyak percobaan masuk…" | Salah kata sandi berkali-kali | Tunggu beberapa menit; bila lupa, lihat 8.4 |
| "Masih ada jawaban yang belum tersimpan di server." (saat mengumpulkan) | Ada jawaban belum terkirim | Perbaiki koneksi dulu, lalu kumpulkan |

---

## 9. Tingkat insiden dan kapan memanggil operator/admin

Mengacu PRD §18.3.

| Tingkat | Contoh | Tindakan pengawas |
|---|---|---|
| **S1 Kritis** | Server/database mati; semua siswa Terputus/Dijeda; halaman login tidak terbuka | Hubungi operator **segera**. Minta siswa tetap di halaman. Ikuti 8.3. Catat jam mulai & selesai. |
| **S2 Tinggi** | Sebagian siswa tidak bisa menyimpan jawaban; banyak "tersimpan di perangkat"; monitor terus "terlambat" | Hubungi operator. Cek apakah satu ruang/AP yang sama. Bantu per siswa (4, 5, 6). Pastikan "Tersimpan di server". |
| **S3 Sedang** | Masalah satu siswa: perangkat rusak, lupa sandi, token terkunci, jawaban offline ditolak | Tangani sendiri (5, 6, 8). Panggil admin untuk sandi. Catat di berita acara. |
| **S4 Rendah** | Tampilan kurang rapi, teks terpotong, tidak mengganggu ujian | Catat dan laporkan setelah ujian. |

Panggil **operator** bila: banyak siswa putus bersamaan, server tidak bisa dibuka, monitor
tidak berganti lebih dari 1 menit, atau Wi-Fi ujian bermasalah.
Panggil **admin** bila: siswa lupa kata sandi, akun siswa tidak ada, siswa tidak melihat
ujian (kemungkinan salah kelas).
Hubungi **guru pemilik** bila: ada salah soal/kunci, jadwal salah, atau keputusan nilai
untuk jawaban yang ditolak.

---

## 10. Setelah ujian

1. Pastikan semua siswa berstatus **Selesai** (sisa waktu habis akan dikumpulkan otomatis).
2. Bila masih ada **Dijeda** atau **Terputus** setelah waktu seharusnya habis, tunggu:
   server akan mengumpulkannya setelah jeda berakhir.
3. Serahkan berita acara ke guru pemilik (daftar insiden, tambah waktu, pindah perangkat,
   jawaban ditolak, catatan pindah tab yang sudah diverifikasi).
4. Tekan **Keluar**.

Admin dapat meninjau semua reset sesi, pindah perangkat, tambah waktu, dan reset kata sandi
lintas ujian di **Administrasi → Riwayat intervensi**.

Fitur yang belum tersedia: ruang tunggu/daftar hadir terpisah, log kejadian per ujian
untuk pengawas (saat ini hanya per siswa di **Riwayat**), dan pengumuman per ruang.
