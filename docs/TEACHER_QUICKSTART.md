# Panduan Cepat Guru — LocalCBT

Panduan ini untuk guru yang membuat soal, menyusun ujian, dan melihat nilai di LocalCBT.
Semua langkah memakai nama tombol yang ada di layar. Bila ada yang berbeda di sekolah
Anda, tanyakan kepada operator/admin.

> Istilah singkat: **bank soal** = kumpulan soal milik Anda. **Ujian** = jadwal + kelas +
> soal yang dipilih dari bank. **Publish** = ujian dikunci dan siap dikerjakan siswa.

---

## 1. Masuk ke LocalCBT

1. Sambungkan laptop/PC ke **jaringan staf** (Wi-Fi/LAN guru, bukan Wi-Fi ujian siswa).
2. Buka alamat portal yang diberikan operator (contoh: `https://cbt.sekolah.test`).
3. Isi **NIS / Username** dengan username guru Anda, lalu **Kata sandi**.
4. Tekan **Masuk**. Anda langsung masuk ke halaman **Guru**.

Catatan:
- Pemisahan jaringan staf dan jaringan siswa diatur di router oleh operator, bukan oleh
  aplikasi. Jangan membuka dashboard guru dari Wi-Fi siswa.
- Salah kata sandi 5 kali dalam 5 menit membuat akun ditahan sebentar. Tunggu beberapa menit.
- Satu akun guru hanya aktif di satu perangkat. Masuk di perangkat baru akan mengeluarkan
  perangkat lama.
- Sesi guru berlaku sampai 12 jam. Tekan **Keluar** di kanan atas bila selesai.

Menu guru ada tiga tab: **Bank soal**, **Ujian**, dan **Pengawasan**.

---

## 2. Bank soal

### 2.1 Membuat bank soal
1. Buka tab **Bank soal**.
2. Di kartu **Bank soal baru**, isi **Judul** dan pilih **Mata pelajaran**.
3. Tekan **Buat bank**.

Bila daftar mata pelajaran kosong, minta admin menambahkannya.

Halaman bank berisi tombol: **Tambah soal**, **Import**, **Pratinjau siswa**,
**Salin ke bank lain**, dan **Bagikan** (hanya pemilik).

### 2.2 Tiga jenis soal

| Jenis di layar | Nama di template import | Aturan |
|---|---|---|
| Pilihan Ganda | `PG` | 2–10 opsi, **tepat satu** kunci |
| Pilihan Ganda Kompleks | `MCMA` | 2–10 opsi, **minimal satu** kunci |
| Benar/Salah per Pernyataan | `KATEGORI` | 2–20 pernyataan, tiap pernyataan diberi kunci Benar atau Salah |

Aturan umum:
- **Bobot** wajib lebih dari 0, boleh 2 angka desimal (contoh `1`, `2.5`).
- Isi opsi/pernyataan dalam satu soal tidak boleh sama.
- Pertanyaan maksimal 10.000 karakter; tiap opsi/pernyataan maksimal 2.000 karakter.

### 2.3 Menambah soal lewat editor
1. Tekan **Tambah soal**.
2. Pilih **Jenis soal** dan isi **Bobot**.
3. (Opsional) pilih **Stimulus bersama** (lihat 2.4).
4. Tulis **Pertanyaan**.
5. (Opsional) unggah **Gambar soal (PNG/JPEG/WebP, maks. 2 MB)**. Sisi gambar maksimal
   4096 piksel. Tekan **Hapus gambar** untuk membatalkan.
6. Isi jawaban:
   - PG / PG Kompleks: isi **Opsi jawaban**, centang **Kunci**. Tekan **Tambah opsi** untuk
     opsi baru.
   - Benar/Salah: isi tiap pernyataan, pilih **Benar** atau **Salah**. Tekan
     **Tambah pernyataan** untuk baris baru.
7. Tekan **Pratinjau siswa** untuk melihat tampilan siswa (tanpa kunci).
8. Tekan **Simpan soal**.

Satu soal hanya bisa memuat **satu gambar** (di pertanyaan). Gambar di dalam opsi belum
tersedia.

Mengubah soal: tekan **Edit** pada soal. Judul editor menunjukkan versinya
(contoh "Edit soal (versi 3)"). Menghapus: tekan **Hapus**. Ujian yang sudah dipublish
**tidak ikut berubah** (lihat bagian 4.3).

### 2.4 Stimulus bersama
Stimulus = bacaan yang dipakai beberapa soal (misalnya satu teks cerita untuk soal 1–3).
1. Di bagian bawah halaman bank, kartu **Stimulus bersama**, isi **Teks stimulus**.
2. Tekan **Tambah stimulus**.
3. Saat membuat/mengedit soal, pilih stimulus itu di kolom **Stimulus bersama**.

Soal yang memakai stimulus yang sama selalu tampil **berdampingan** saat ujian, walaupun
urutan soal diacak.

Stimulus berupa gambar belum bisa dibuat dari layar ini (baru teks).

### 2.5 Import soal dari XLSX atau DOCX
1. Di halaman bank, tekan **Import**.
2. Unduh template: tautan **XLSX** (satu baris = satu soal) atau **DOCX** (satu tabel = satu soal).
3. Isi template, simpan.
4. Pilih berkas di **Berkas XLSX atau DOCX**, tekan **Periksa berkas**.
5. Baca hasilnya: "X dari Y soal valid". Bila ada masalah, tabel menunjukkan
   **Soal ke**, **Kolom**, dan **Masalah**. Perbaiki berkas, lalu periksa ulang.
6. Bila semua valid, tekan **Simpan N soal**.

Penting: **tidak ada soal yang disimpan** sampai semua soal di berkas valid.

**Kolom template (harus persis, berurutan, di baris pertama sheet pertama):**

| Kolom | Isi | Contoh |
|---|---|---|
| `Jenis` | `PG`, `MCMA`, atau `KATEGORI` | `PG` |
| `Stimulus` | Teks bacaan (boleh kosong) | `Perhatikan bilangan 2, 3, 4, 9.` |
| `Pertanyaan` | Teks soal | `Hasil dari 12 × 3 adalah …` |
| `Bobot` | Angka > 0; koma atau titik; kosong = 1 | `2` atau `2,5` |
| `Kunci` | PG: satu huruf. MCMA: huruf dipisah koma. KATEGORI: `B`/`S` per pernyataan | `B` · `A,C` · `B,S,B` |
| `Opsi A` … `Opsi E` | Teks opsi. Untuk KATEGORI: teks pernyataan | `36` |

Aturan import:
- Huruf besar/kecil pada judul kolom tidak masalah, tetapi **urutannya harus sama**.
- Kunci harus huruf dari opsi yang **terisi**. Contoh: kunci `E` ditolak bila `Opsi E` kosong.
- KATEGORI: jumlah huruf `B`/`S` harus sama dengan jumlah pernyataan yang terisi.
  `B` = Benar, `S` = Salah.
- Lewat import maksimal **5 opsi/pernyataan** (A–E). Butuh lebih? Tambahkan lewat editor.
- Soal dengan teks `Stimulus` yang **sama persis** dalam satu berkas dijadikan satu
  stimulus bersama.
- **Gambar tidak ikut diimport.** Tambahkan gambar lewat **Edit** setelah import.
- Berkas maksimal **2 MB** dan **500 soal**.
- DOCX: setiap tabel punya 2 kolom, `label | isi`. Label sama dengan nama kolom di atas
  (boleh diakhiri titik dua, misalnya `Kunci:`). Gambar atau tabel di dalam sel ditolak.

### 2.6 Berbagi dan menyalin bank
Hanya pemilik bank yang bisa berbagi.
1. Di halaman bank, tekan **Bagikan**.
2. Pilih **Guru** dan **Akses**, tekan **Simpan akses**.
3. Untuk mencabut, tekan **Cabut** di samping nama guru.

| Akses | Artinya |
|---|---|
| Lihat (termasuk kunci) | Melihat soal **dan kunci**, tidak bisa memakai di ujian |
| Lihat & salin | Seperti di atas + boleh menyalin ke bank sendiri + boleh memakai soal di ujian |
| Edit soal | Seperti di atas + boleh menambah/mengubah/menghapus soal di bank ini |

Bank yang dibagikan muncul di bagian **Dibagikan kepada saya**.

Menyalin: tekan **Salin ke bank lain**, pilih **Bank tujuan**, tekan **Salin soal**.
Semua soal aktif disalin (stimulus ikut tersalin dan tetap berkelompok).

---

## 3. Membuat ujian

1. Buka tab **Ujian**, tekan **Buat ujian**.
2. Isi **Judul** dan **Mata pelajaran**.
3. Centang **Kelas peserta**. Hanya kelas yang Anda ajar untuk mapel itu yang muncul.
   Bila kosong, minta admin membuat penugasan mengajar.
4. Isi **Jadwal & akses**:
   - **Mulai dibuka**: siswa boleh mulai sejak waktu ini.
   - **Batas akhir mulai**: siswa tidak bisa mulai setelah waktu ini.
   - **Durasi (menit)**: 1–1440 menit. Waktu dihitung **per siswa** sejak ia menekan Mulai.
   - **Token ujian**: 4–32 karakter. **Catat token ini.** Token tidak pernah ditampilkan lagi.
5. Pilih soal di bagian **Soal (N dipilih)**. Yang muncul hanya bank dengan mapel yang sama,
   milik Anda atau dibagikan dengan akses "Lihat & salin"/"Edit soal".
6. Atur **Nilai & pembahasan** (lihat bagian 6).
7. Tekan **Simpan draft**.

Catatan jadwal:
- Siswa yang mulai mendekati **Batas akhir mulai** tetap mendapat durasi penuh. Jadi ujian
  bisa berakhir sampai "Batas akhir mulai + Durasi" (ditambah jeda/tambahan waktu).
- Zona waktu mengikuti perangkat Anda (tertulis di layar).

**Pengacakan:** urutan soal dan opsi **selalu diacak per siswa**. Tidak ada pilihan untuk
mematikannya. Soal dengan stimulus sama tetap berdampingan.

---

## 4. Pratinjau, publish, dan setelah publish

### 4.1 Pratinjau
1. Di daftar ujian, tekan **Edit** pada ujian draft.
2. Tekan **Pratinjau & validasi**. Anda melihat urutan acak seperti satu peserta, plus
   daftar masalah bila ada.
3. Tekan **Acak ulang** untuk melihat contoh urutan lain.

### 4.2 Publish
1. Tekan **Publish…**.
2. Baca teks aturan penilaian (lihat bagian 7).
3. Centang **Saya menyetujui aturan penilaian PROPOSED-1 untuk ujian ini**.
4. Tekan **Publish & bekukan soal**.

Publish ditolak bila: ada kelas yang tidak Anda ajar, ada soal yang sudah dihapus/beda
mapel/tidak boleh dipakai, belum ada kelas atau soal, atau **Batas akhir mulai** sudah lewat.

### 4.3 Soal dibekukan (snapshot)
Saat publish, isi soal, opsi, kunci, dan bobot **disalin dan dikunci**. Publish dan tarik
publish tercatat di log audit. Akibatnya:
- Mengedit atau menghapus soal di bank **tidak mengubah** ujian yang sudah dipublish.
- Nilai siswa selalu dihitung dari salinan beku ini.
- Salah kunci setelah publish **tidak bisa diperbaiki** dari bank. Periksa dengan teliti
  sebelum publish.

### 4.4 Setelah publish
Status ujian: **Terjadwal** → **Berlangsung** → **Selesai**.

Yang masih bisa diubah:
- **Ganti token**: isi **Token baru**, tekan **Ganti token**. Siswa yang sudah mulai tidak
  terpengaruh. Penggantian tercatat di log audit (siapa dan kapan; tokennya sendiri tidak
  disimpan).
- **Nilai & pembahasan**: ubah lalu tekan **Simpan kebijakan nilai**.
- **Pengawas**: tugaskan atau lepas pengawas.

Yang tidak bisa diubah: jadwal, durasi, kelas, dan soal.
- Tombol **Tarik ke draft** hanya berhasil **sebelum jadwal dibuka** dan **belum ada siswa
  yang mulai**. Setelah itu ujian tidak bisa diubah sama sekali.

---

## 5. Pengawasan

### 5.1 Menugaskan pengawas
1. Buka ujian yang sudah dipublish (tombol **Detail**).
2. Di kartu **Pengawas**, pilih nama di **Tugaskan pengawas**, tekan **Tugaskan**.
3. Tekan **Lepas** untuk mencabut.

Anda **selalu** bisa mengawasi ujian sendiri. Pengawas yang ditugaskan hanya melihat ujian
itu, tanpa kunci jawaban dan tanpa nilai. Pengawas **tidak bisa melihat token**, jadi
berikan token kepada pengawas secara langsung.

### 5.2 Memantau
- Ujian sendiri: tekan **Pantau** di halaman ujian.
- Ditugaskan mengawasi ujian guru lain: buka tab **Pengawasan** di menu guru. Daftarnya
  berisi ujian Anda sendiri dan ujian yang menugaskan Anda sebagai pengawas.

Cara kerja monitor, jeda otomatis, tambah waktu, dan pindah perangkat dijelaskan di
**[SOP Pengawas](PROCTOR_SOP.md)**.

---

## 6. Nilai, publikasi, dan pembahasan

### 6.1 Kapan siswa melihat nilai
Pilih di **Kapan siswa melihat nilai**:

| Pilihan | Yang dilihat siswa |
|---|---|
| Hanya guru (default) | Hanya bukti pengumpulan, tanpa nilai |
| Langsung setelah siswa mengumpulkan | Nilai muncul begitu selesai dinilai |
| Setelah guru mempublikasikan nilai | Nilai muncul setelah Anda menekan **Publikasikan nilai** |

### 6.2 Pembahasan
- Centang **Buka pembahasan (soal dan jawaban sendiri) untuk siswa**.
- (Opsional) isi **Pembahasan dibuka mulai**.
- (Opsional) centang **Tampilkan kunci jawaban**.

Pembahasan baru terbuka bila **semua** syarat terpenuhi: dicentang, waktu "dibuka mulai"
sudah lewat, **dan ujian sudah usai** (batas akhir mulai + durasi lewat, dan tidak ada
siswa yang masih mengerjakan). Jadi kunci tidak bocor saat teman masih ujian.
Nilai per soal hanya muncul di pembahasan bila nilai juga sudah boleh dilihat.

Teks penjelasan/uraian jawaban belum tersedia. "Pembahasan" saat ini berarti siswa
melihat soal dan jawabannya sendiri (dan kunci bila diizinkan).

### 6.3 Halaman hasil
1. Di halaman ujian, tekan **Hasil & nilai**.
2. Tabel berisi **Nama**, **Kelas**, **Status**, **Nilai**.

| Status | Arti |
|---|---|
| Belum mulai | Siswa belum menekan Mulai |
| Mengerjakan | Masih mengerjakan |
| Dijeda | Koneksi terputus, waktu sedang dibekukan |
| Penilaian tertunda | Sudah dikumpulkan, nilai belum terhitung |
| Dinilai | Nilai sudah ada |

- **Nilai ulang N yang tertunda**: muncul bila ada status "Penilaian tertunda". Tekan untuk
  menghitung ulang. Nilai yang sudah ada tidak diubah.
- **Publikasikan nilai** / **Tarik publikasi nilai**: hanya muncul bila pilihan
  "Setelah guru mempublikasikan nilai".
- **Unduh XLSX**: berkas `nilai-<id>.xlsx`, sheet "Nilai", kolom `NIS`, `Nama`, `Kelas`,
  `Status`, `Nilai`, `Maks`, lalu `S1`, `S2`, … (nilai per soal sesuai **urutan soal saat
  publish**, bukan urutan acak siswa).

---

## 7. Aturan penilaian (PROPOSED-1)

> **Perhatian:** rumus nilai sebagian (partial credit) ini **masih usulan** dan **belum
> disahkan sekolah** (PRD BR-07 dan OQ-01). Mintalah persetujuan tertulis dari
> guru/kurikulum sebelum dipakai untuk nilai resmi. Saat publish, Anda wajib mencentang
> persetujuan aturan ini.

Aturan umum:
- Jawaban kosong = 0.
- Nilai tiap soal dibulatkan **2 desimal** (0,005 ke atas). Total = jumlah nilai soal.
- Nilai maksimal = jumlah bobot semua soal.

### 7.1 Pilihan Ganda
Bobot penuh bila jawaban tepat, selain itu 0.

> Contoh: bobot 2, kunci B. Siswa memilih B → **2,00**. Memilih C → **0**.

### 7.2 Pilihan Ganda Kompleks
`nilai = bobot × (opsi benar dipilih ÷ jumlah opsi benar − opsi salah dipilih ÷ jumlah opsi salah)`,
dibatasi 0 sampai bobot. Bila semua opsi adalah kunci (tidak ada opsi salah), hanya bagian
pertama yang dipakai.

> Contoh: bobot 2, opsi A–E, kunci A dan C (2 benar, 3 salah). Siswa memilih **A dan B**.
> 2 × (1/2 − 1/3) = 2 × 1/6 = 0,333… → **0,33**.

| Pilihan siswa | Hitungan | Nilai |
|---|---|---|
| A, C | 2 × (2/2 − 0/3) | 2,00 |
| A saja | 2 × (1/2 − 0) | 1,00 |
| B, D | 2 × (0 − 2/3) → negatif, jadi 0 | 0,00 |
| A, B, C, D, E | 2 × (2/2 − 3/3) | 0,00 |

### 7.3 Benar/Salah per Pernyataan
`nilai = bobot × (pernyataan dijawab benar ÷ jumlah pernyataan)`. Pernyataan yang tidak
dijawab bernilai 0. Jawaban salah tidak mengurangi nilai.

> Contoh: bobot 3, 4 pernyataan. Siswa menjawab 3 dengan benar, 1 dikosongkan.
> 3 × 3/4 = **2,25**.

---

## 8. Masalah yang sering muncul

| Pesan / gejala | Penyebab | Yang dilakukan |
|---|---|---|
| "Kolom tidak sesuai template. Unduh template terbaru." | Judul kolom salah/berbeda urutan | Pakai template yang diunduh dari layar Import |
| "Kunci harus huruf opsi yang terisi…" | Kunci menunjuk opsi kosong | Perbaiki kolom `Kunci` atau isi opsinya |
| "Ada kelas yang tidak Anda ajar untuk mata pelajaran ini." | Penugasan mengajar belum ada | Minta admin menambah penugasan mengajar |
| "Batas akhir mulai ujian sudah lewat…" | Jadwal sudah lewat saat publish | Ubah jadwal di draft, lalu publish lagi |
| "Ujian sudah dipublish dan tidak bisa diubah." | Mengedit ujian yang sudah publish | Tarik ke draft (bila belum dibuka) atau buat ujian baru |
| Siswa tidak melihat ujian | Kelas siswa tidak dipilih, atau belum publish | Periksa kelas di ujian; tanyakan admin soal keanggotaan kelas |
| Siswa lupa kata sandi | — | Hubungi admin/operator (lihat SOP Pengawas) |
