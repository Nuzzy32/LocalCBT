# DISC-02 Pengesahan Aturan Nilai oleh Guru

**Tujuan:** guru/kurikulum memeriksa cara LocalCBT menghitung nilai, lalu menyetujui atau
mengubahnya **sebelum** nilai dipakai resmi. Aturan yang sekarang terpasang bernama **PROPOSED-1**.
Aturan ini usulan teknis dan belum disahkan sekolah (PRD §9, OQ-01, ADR-005).

**Lulus bila:** semua contoh di Bagian 1 diberi tanda setuju/tidak, Bagian 2 dipilih, dan lembar ini
ditandatangani.

Semua angka "Nilai sistem" di bawah **dihitung langsung oleh kode penilaian LocalCBT**
(`services/api/app/scoring.py`), bukan hitungan tangan.

Cara membaca:
- **Bobot** = nilai maksimal soal itu.
- Huruf opsi (A, B, C…) adalah urutan saat guru menulis soal. Di layar siswa urutan opsi diacak,
  tetapi nilai tetap dihitung dari opsi yang dipilih, bukan dari posisinya.
- Bila tidak setuju, tulis nilai yang benar menurut Bapak/Ibu di kolom terakhir.

---

## Aturan PROPOSED-1 (singkat)

| Jenis soal | Rumus |
|---|---|
| **Pilihan Ganda** | Benar = bobot penuh. Salah atau kosong = 0. |
| **Pilihan Ganda Kompleks** (lebih dari satu jawaban) | bobot × (opsi benar yang dipilih ÷ jumlah opsi benar − opsi salah yang dipilih ÷ jumlah opsi salah). Hasil di bawah 0 dianggap 0. Memilih opsi salah **mengurangi** nilai, supaya siswa tidak untung dengan mencentang semua. |
| **Benar/Salah per Pernyataan** | bobot × (pernyataan yang dijawab benar ÷ jumlah pernyataan). Pernyataan kosong = 0. Jawaban salah **tidak** mengurangi. |
| **Pembulatan** | Nilai tiap soal dibulatkan 2 desimal (0,005 ke atas), lalu dijumlah. |
| **Tampilan** | Siswa dan guru melihat "Nilai: *total* dari *jumlah bobot*". |

---

## Bagian 1. Contoh soal dan nilai

### Pilihan Ganda: bobot 2, opsi A–D, kunci **B**

| No | Jawaban siswa | Hitungan | Nilai sistem | Setuju? | Bila tidak, nilai yang benar |
|---|---|---|---|---|---|
| 1 | B | benar → bobot penuh | **2,00** | ☐ Ya ☐ Tidak | |
| 2 | C | salah → 0 | **0,00** | ☐ Ya ☐ Tidak | |
| 3 | (kosong) | kosong → 0 | **0,00** | ☐ Ya ☐ Tidak | |

### Pilihan Ganda Kompleks: bobot 2, opsi A–E, kunci **A dan C** (2 benar, 3 salah)

| No | Jawaban siswa | Hitungan | Nilai sistem | Setuju? | Bila tidak, nilai yang benar |
|---|---|---|---|---|---|
| 4 | A, C | 2 × (2/2 − 0/3) | **2,00** | ☐ Ya ☐ Tidak | |
| 5 | A saja | 2 × (1/2 − 0/3) | **1,00** | ☐ Ya ☐ Tidak | |
| 6 | A, B | 2 × (1/2 − 1/3) = 0,333… | **0,33** | ☐ Ya ☐ Tidak | |
| 7 | A, B, C | 2 × (2/2 − 1/3) = 1,333… | **1,33** | ☐ Ya ☐ Tidak | |
| 8 | B, D | 2 × (0/2 − 2/3) → negatif, jadi 0 | **0,00** | ☐ Ya ☐ Tidak | |
| 9 | A, B, C, D, E (semua) | 2 × (2/2 − 3/3) | **0,00** | ☐ Ya ☐ Tidak | |
| 10 | (kosong) | kosong → 0 | **0,00** | ☐ Ya ☐ Tidak | |

### Pilihan Ganda Kompleks: bobot 10, opsi A–E, kunci **A, C, E** (3 benar, 2 salah)

| No | Jawaban siswa | Hitungan | Nilai sistem | Setuju? | Bila tidak, nilai yang benar |
|---|---|---|---|---|---|
| 11 | A, C | 10 × (2/3 − 0/2) = 6,666… | **6,67** | ☐ Ya ☐ Tidak | |
| 12 | A, B, C, E | 10 × (3/3 − 1/2) | **5,00** | ☐ Ya ☐ Tidak | |

### Pilihan Ganda Kompleks tanpa opsi salah: bobot 3, opsi A–C, kunci **A, B, C** (semua benar)

| No | Jawaban siswa | Hitungan | Nilai sistem | Setuju? | Bila tidak, nilai yang benar |
|---|---|---|---|---|---|
| 13 | A, B | 3 × 2/3 (tidak ada opsi salah, jadi hanya bagian pertama) | **2,00** | ☐ Ya ☐ Tidak | |

### Benar/Salah per Pernyataan: bobot 3, 4 pernyataan, kunci **B, S, B, S**

| No | Jawaban siswa | Hitungan | Nilai sistem | Setuju? | Bila tidak, nilai yang benar |
|---|---|---|---|---|---|
| 14 | B, S, B, S (semua tepat) | 3 × 4/4 | **3,00** | ☐ Ya ☐ Tidak | |
| 15 | B, S, B, (kosong) | 3 × 3/4 | **2,25** | ☐ Ya ☐ Tidak | |
| 16 | B, S, S, B (2 tepat, 2 keliru) | 3 × 2/4, keliru tidak mengurangi | **1,50** | ☐ Ya ☐ Tidak | |

### Benar/Salah per Pernyataan: bobot 10, 3 pernyataan, kunci **B, B, S**

| No | Jawaban siswa | Hitungan | Nilai sistem | Setuju? | Bila tidak, nilai yang benar |
|---|---|---|---|---|---|
| 17 | B, B, B (2 tepat) | 10 × 2/3 = 6,666… | **6,67** | ☐ Ya ☐ Tidak | |

### Pembulatan total: 3 soal Pilihan Ganda Kompleks, masing-masing bobot 1, opsi A–D, kunci A, B, C

Siswa memilih **A saja** di ketiga soal. Tiap soal bernilai 1 × 1/3 = 0,333…

| No | Cara | Hitungan | Hasil | Setuju? |
|---|---|---|---|---|
| 18 | Sekarang: bulatkan per soal, lalu jumlah | 0,33 + 0,33 + 0,33 | **0,99** dari 3 | ☐ Ya ☐ Tidak |
| 19 | Pembanding: jumlah dulu, baru bulatkan | 1/3 + 1/3 + 1/3 = 1 | **1,00** dari 3 | ☐ Ya ☐ Tidak |

---

## Bagian 2. Keputusan yang perlu dipilih

### 2.1 Rumus Pilihan Ganda Kompleks

Perbandingan untuk contoh 4–12 (bobot dan kunci sama):

| No | Jawaban | **A. PROPOSED-1** (sekarang) | **B. Per opsi** | **C. Semua atau nol** |
|---|---|---|---|---|
| 4 | A, C | 2,00 | 2,00 | 2,00 |
| 5 | A | 1,00 | 1,60 | 0,00 |
| 6 | A, B | 0,33 | 1,20 | 0,00 |
| 7 | A, B, C | 1,33 | 1,60 | 0,00 |
| 8 | B, D | 0,00 | 0,40 | 0,00 |
| 9 | semua | 0,00 | 0,80 | 0,00 |
| 11 | A, C | 6,67 | 8,00 | 0,00 |
| 12 | A, B, C, E | 5,00 | 8,00 | 0,00 |

- **A. PROPOSED-1:** opsi benar menambah, opsi salah mengurangi. Mencentang semua opsi = 0.
- **B. Per opsi:** setiap opsi dinilai seperti soal benar/salah kecil (dicentang atau tidak, tepat
  atau keliru). Siswa tetap dapat nilai walau hanya memilih opsi salah (contoh 8: 0,40).
- **C. Semua atau nol:** bobot penuh hanya bila pilihannya persis sama dengan kunci.

Pilihan: ☐ A ☐ B ☐ C ☐ Lainnya: ____________________________________

### 2.2 Rumus Benar/Salah per Pernyataan

| No | Jawaban | **A. PROPOSED-1** (sekarang) | **C. Semua atau nol** |
|---|---|---|---|
| 14 | semua tepat | 3,00 | 3,00 |
| 15 | 3 tepat, 1 kosong | 2,25 | 0,00 |
| 16 | 2 tepat, 2 keliru | 1,50 | 0,00 |
| 17 | 2 dari 3 tepat | 6,67 | 0,00 |

Pilihan: ☐ A ☐ C ☐ Lainnya: ____________________________________

### 2.3 Pilihan Ganda Kompleks yang semua opsinya kunci (contoh 13)

Saat ini soal seperti ini **boleh** dibuat dan dinilai dengan bagian pertama rumus saja. PRD §9.5
mengusulkan soal seperti ini **ditolak** saat publish, karena siswa bisa mendapat nilai penuh
dengan mencentang semua opsi.

☐ Tetap boleh (seperti sekarang) ☐ Tolak saat publish

### 2.4 Pembulatan

| Pertanyaan | Pilihan |
|---|---|
| Kapan dibulatkan? | ☐ Per soal lalu dijumlah (sekarang, contoh 18) ☐ Dijumlah dulu, dibulatkan di akhir (contoh 19) |
| Berapa desimal? | ☐ 2 desimal (sekarang) ☐ 1 desimal ☐ Bilangan bulat ☐ Lainnya: ____ |
| Arah pembulatan | ☐ Setengah ke atas (sekarang: 0,005 → 0,01) ☐ Lainnya: ____ |

### 2.5 Bentuk nilai yang dilihat siswa dan guru

Saat ini: "Nilai: 7,33 dari 10".

☐ Cukup seperti sekarang ☐ Tambahkan skala 0–100: (total ÷ jumlah bobot) × 100 ☐ Lainnya: ____

### 2.6 Nilai minimal per soal

Nilai per soal tidak pernah negatif (paling rendah 0). ☐ Setuju ☐ Tidak

---

## Setelah lembar ini ditandatangani

- Bila semua pilihan sama dengan PROPOSED-1, aturan itu dinaikkan statusnya menjadi aturan resmi
  sekolah.
- Bila ada yang berbeda, pengembang membuat aturan versi baru, menambah tes otomatis dengan
  **contoh-contoh di lembar ini sebagai jawaban yang benar**, lalu meminta guru memeriksa ulang
  nilai contohnya sebelum rilis.
- Setiap ujian menyimpan versi aturan yang dipakai saat dipublikasikan. Ujian lama tidak berubah
  nilainya ketika aturan diganti.

Catatan guru:

&nbsp;

&nbsp;

| | Nama | Mata pelajaran / jabatan | Tanda tangan | Tanggal |
|---|---|---|---|---|
| Guru | | | | |
| Guru | | | | |
| Wakasek Kurikulum | | | | |
