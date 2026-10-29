# DISC-04 Uji Sertifikat HTTPS di Perangkat Siswa

**Tujuan:** memastikan semua jenis perangkat siswa bisa membuka portal ujian lewat HTTPS **tanpa
peringatan sertifikat**, di jaringan ujian yang tidak tersambung internet.

**Lulus bila:** setiap jenis perangkat di Bagian 3 berhasil membuka portal, login, dan menyimpan satu
jawaban, **tanpa menekan "Lanjutkan ke situs (tidak aman)"** sekali pun.

**Gagal = berhenti (go/no-go Gate 0):** bila satu jenis perangkat yang dipakai siswa tidak bisa
lulus dengan strategi mana pun, M9 tidak boleh diklaim siap rilis. Desainnya ditinjau ulang bersama
sekolah.

Menjawab: ADR-003, ADR-009, DEC-05 (semuanya masih OPEN).

> **Jangan pernah** meminta siswa melewati peringatan sertifikat. Itu melatih siswa mengabaikan
> tanda bahaya. Portal juga mengirim HSTS, jadi setelah perangkat pernah membuka portal, browser
> tidak lagi menawarkan tombol "lanjutkan".

---

## 1. Dua strategi yang diuji

| | **S1. CA lokal** (terpasang sekarang) | **S2. Sertifikat publik untuk subdomain sekolah** |
|---|---|---|
| Cara kerja | Caddy di server membuat "CA lokal" sendiri. Setiap perangkat harus **memasang dan mempercayai** sertifikat root CA itu. | Sertifikat resmi (mis. Let's Encrypt) untuk `cbt.<domain-sekolah>`. DNS lokal sekolah mengarahkan nama itu ke IP server. |
| Yang dikerjakan di HP siswa | Pasang sertifikat root, sekali per perangkat. Langkahnya berbeda per merek dan OS (lihat Bagian 2). | **Tidak ada.** |
| Syarat dari sekolah | Izin memasang sertifikat di HP pribadi siswa. | Sekolah punya domain dan bisa mengubah DNS-nya (DISC-01 §G). Server sesekali perlu internet untuk memperpanjang sertifikat (masa berlaku maksimal 90 hari). |
| Risiko | Sertifikat root yang dipasang membuat perangkat itu mempercayai **apa pun** yang ditandatangani server sekolah, termasuk tiruan situs lain. Kunci CA harus dijaga ketat. Siswa sebaiknya menghapusnya setelah tidak bersekolah. | Bila perpanjangan gagal, sertifikat kedaluwarsa dan semua perangkat menolak portal. Preflight menampilkan sisa hari berlakunya. |
| Status kode | Sudah jalan (`tls internal` di `infrastructure/proxy/Caddyfile`). | **Belum didukung.** Perlu Caddy dengan modul DNS penyedia domain sekolah dan perubahan kecil di Caddyfile. Dikerjakan bila sekolah memilih S2. |

Bila sekolah tidak punya domain, hanya S1 yang bisa diuji.

---

## 2. Persiapan S1: memasang sertifikat root

Sertifikat root CA lokal ada di server:

| Server | Lokasi |
|---|---|
| macOS | `/Library/Application Support/LocalCBT/caddy/pki/authorities/local/root.crt` |
| Windows | `C:\LocalCBT\caddy\caddy\pki\authorities\local\root.crt` |

Salin **hanya `root.crt`**. Jangan salin `root.key` atau berkas lain di folder itu. Siapa pun yang
memegang `root.key` bisa meniru situs apa pun bagi perangkat yang sudah memasang sertifikat ini.

Bagikan `root.crt` lewat flashdisk, AirDrop, atau unggahan lokal. Catat sidik jari (SHA-256)
sertifikat dari server, lalu cocokkan di perangkat setelah dipasang.

| Perangkat | Langkah (nama menu bisa berbeda per merek/versi, catat yang sebenarnya) |
|---|---|
| **Android** | Pengaturan → Keamanan → Enkripsi & kredensial → Pasang sertifikat → **Sertifikat CA** → pilih `root.crt`. |
| **iPhone / iPad** | Buka `root.crt` di Safari → izinkan unduh profil → Pengaturan → *Profil Diunduh* → Instal. Lalu Pengaturan → Umum → Mengenai → **Pengaturan Kepercayaan Sertifikat** → aktifkan sertifikat itu. Tanpa langkah kedua, sertifikat belum dipercaya. |
| **Windows** | Klik dua kali `root.crt` → Install Certificate → *Local Machine* → *Trusted Root Certification Authorities*. |
| **macOS** | Buka `root.crt` di Keychain Access → keychain *System* → klik dua kali sertifikat → Trust → *Always Trust*. |
| **Firefox** (semua OS) | Firefox bisa memakai daftar sertifikatnya sendiri. Bila masih ada peringatan: Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import. |

---

## 3. Lembar uji per perangkat

Uji dari **SSID ujian** dengan internet sudah diblokir (ADMIN_GUIDE §4.1). Pakai akun siswa uji,
bukan akun siswa asli. Usahakan setiap baris adalah perangkat milik siswa yang sebenarnya,
termasuk HP Android lama dan murah yang paling sering dipakai.

Alamat portal yang diuji: `https://______________________`  Strategi: ☐ S1 ☐ S2

| No | Perangkat (merek, model) | OS & versi | Browser & versi | 1. Terbuka tanpa peringatan | 2. Ikon gembok, nama cocok | 3. Login siswa | 4. Jawab 1 soal → "Tersimpan di server" | 5. Muat ulang, masih "Tersimpan di server" | Lama pasang sertifikat (menit) | Catatan |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | Android | Chrome | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 2 | | Android | Samsung Internet / bawaan | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 3 | | Android (versi tertua di DISC-01) | Chrome | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 4 | | iOS | Safari | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 5 | | iOS | Chrome | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 6 | | Windows | Chrome / Edge | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 7 | | Windows | Firefox | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 8 | | macOS | Safari | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 9 | | | | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 10 | | | | ☐ | ☐ | ☐ | ☐ | ☐ | | |

Langkah 1–2 cukup dengan membuka portal. Langkah 3–5 memakai ujian latihan yang sudah dipublikasikan.

### Perangkat staf

| No | Perangkat | Browser | Portal terbuka tanpa peringatan | Monitor pengawas: "Diperbarui HH:MM" berganti tiap beberapa detik (WebSocket) |
|---|---|---|---|---|
| 1 | | | ☐ | ☐ |
| 2 | | | ☐ | ☐ |

---

## 4. Uji tambahan (pengaturan DNS di perangkat)

Saat internet diblokir, beberapa pengaturan bisa membuat nama portal tidak ditemukan. Uji pada
minimal satu perangkat masing-masing, lalu catat hasilnya.

| Kondisi | Cara | Portal terbuka? | Catatan |
|---|---|---|---|
| Android **Private DNS** diisi nama penyedia (mis. `dns.google`) | Pengaturan → Jaringan → DNS Pribadi | ☐ Ya ☐ Tidak | |
| Android Private DNS **Otomatis** | sama | ☐ Ya ☐ Tidak | |
| Chrome **Secure DNS** aktif dengan penyedia tertentu | Chrome → Setelan → Privasi → Gunakan DNS aman | ☐ Ya ☐ Tidak | |
| iPhone **iCloud Private Relay** aktif (bila ada) | Pengaturan → nama Apple ID → iCloud → Private Relay | ☐ Ya ☐ Tidak | |
| Membuka lewat **alamat IP** server, bukan nama | `https://<IP>` | Harus **muncul peringatan** (sertifikat untuk nama, bukan IP). Jangan dilanjutkan. | |

Bila ada kondisi yang gagal, tuliskan langkah yang harus diminta pengawas ke siswa (mis. "matikan
DNS Pribadi") ke dalam SOP pengawas.

---

## 5. Cek di server

| ✓ | Langkah |
|---|---|
| ☐ | Control Center → **Jaringan** → **Jalankan preflight**: baris **dns** dan **https** berstatus OK, dan sisa hari berlaku sertifikat terbaca. |
| ☐ | Untuk S1: sidik jari `root.crt` di server sama dengan yang terpasang di perangkat uji. |
| ☐ | Untuk S1: `root.key` hanya bisa dibaca oleh akun layanan dan admin server. |

---

## 6. Kesimpulan

| Pertanyaan | Jawaban |
|---|---|
| Strategi yang dipilih | ☐ S1 ☐ S2 |
| Semua jenis perangkat siswa lulus? | ☐ Ya ☐ Tidak, yang gagal: |
| Rata-rata waktu pasang sertifikat per HP (S1) | |
| Siapa yang memasang sertifikat di HP siswa, dan kapan (S1) | |
| Langkah tambahan yang perlu masuk SOP pengawas | |

| | Nama | Tanda tangan | Tanggal |
|---|---|---|---|
| Operator sekolah | | | |
| Pengembang | | | |
