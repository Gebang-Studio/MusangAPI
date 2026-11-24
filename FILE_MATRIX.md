# FILE_MATRIX — file buatan muse di /chat

2026-11-24. Permintaan ke muse: 15/15 (batas yang disepakati). Backup riwayat: scratchpad/backup2/chats.json.

## Akar masalah (dari event mentah, bukan dugaan)

Rekaman CDP di tab muse milik engine (`scratchpad/raw/*.json`), fixture anonim di `tests/fixtures/`:

1. Muse **memang membuat file** di VM-nya (`files.updated` → `workspace/your_files/<nama>`).
2. File dikirim sebagai event **`delta.presentation` `kind:"file"`** dengan `message_id` lain (widget), berisi
   `label`, `mime`, `byte_len`, `path: sandbox://…`, `variants.original: https://<vm>.metaaivm.com/media/raw/…`.
   `delta.message_done` hanya berisi teks ("Selesai, ini filenya:"). Engine hanya membaca event ber-`message_id`
   jawaban → file terbuang. Itulah "ini filenya" tanpa file.
3. Muse kadang membalas dalam **beberapa pesan** di sesi yang sama ("Saya kirim filenya begitu sudah jadi" → pesan
   lanjutan berisi file). Engine berhenti di `message_done` pertama → lanjutan + file hilang (06_csv, docx, pdf).

Cara mengambil byte, diuji satu per satu:

| Cara | Hasil | Bukti |
|------|-------|-------|
| `fetch(variants.original)` dari halaman | ❌ `TypeError: Failed to fetch` | 05_zip, 06_csv |
| CDP `Network.loadNetworkResource` | ❌ `net::ERR_NAME_NOT_RESOLVED` (host VM tidak bisa di-resolve dari browser ini) | 06_csv |
| `/api/session/fileserver-read?path=` di muse.ai | ❌ mengembalikan HTML aplikasi (SPA), bukan file | 01 |
| **UI muse: kartu file → panel → More actions → Download, tangkap Blob** | ✅ 307 B zip, SHA-256 cocok JS vs Python, `unzip -t` OK | 08_zip |

Kode unduh muse (bundle `286is7lumaj4v.js`): `URL.createObjectURL(blob)` + `<a download=nama>.click()`; satu-satunya
tipe yang diblokir adalah audio di mode non-standard.

## Matriks (live di /chat, setelah perbaikan)

| Jenis | Muse membuat? | Sampai ke /chat? | Bukti |
|-------|---------------|------------------|-------|
| .txt | ✅ | ✅ | isi = lirik yang diminta; SHA-256 server = unduhan `3383b55c…`; header attachment+nosniff+sandbox |
| .zip (3 file) | ✅ | ✅ | `unzip -t` OK; README.md/main.py/data.json isinya tepat |
| .pdf | ✅ | ✅ | `file`: PDF 1.4, 1 halaman; dirender `sips` → judul + 3 poin benar |
| .docx | ✅ (lewat pesan lanjutan) | ✅ | OOXML, `unzip -t` OK, `textutil` → 1 paragraf surat izin; 3 pesan muse tersambung |
| .md nama "Catatan Café 2026.md" | ✅ | ✅ | `filename*=utf-8''Catatan%20Caf%C3%A9%202026.md`, isi `# Catatan` |
| .csv nama "nilai siswa.csv" | ✅ | ✅ (setelah percobaan ulang menu) | isi `nama,nilai / Budi,90` |
| .json | ✅ | ✅ | `{"aktif":true}` valid |
| beberapa file sekaligus | ✅ | ✅ | md + json (uji 13), csv (uji 15) |
| file besar 6 MB (besar.txt) | ✅ (muse: 6,0 MB, 262.144 baris) | ❌ | gagal dengan respons CDP kosong `{}`; transfer 1–12 MB lewat CDP sendiri terbukti lancar (bigtest.py), jadi bukan batas ukuran. Penyebab belum terbukti; log sekarang mencatat respons CDP lengkap. Kuota muse habis untuk uji ulang |
| .py | ➖ | ➖ | hanya di dalam zip (main.py benar), tidak diminta terpisah — kuota |
| reload /chat | — | ✅ | tautan tetap ada (riwayat di server) |
| restart server | — | ✅ | file yang dibuat sebelum 4× restart → 200 |
| hapus percakapan | — | ✅ | DELETE 200 → file 404 & hilang dari disk |

## Bug log

| Bug | Penyebab | Perbaikan | Tes (gagal di kode lama) |
|-----|----------|-----------|---------------------------|
| F1 "ini filenya" tanpa file | `delta.presentation kind=file` diabaikan | `_NetReply` mengumpulkan file per sesi; engine mengambil byte lewat UI muse, `file_sink` menyimpan ke `data/files/` | test_chat_files.py (fixture mentah) |
| F2 pesan lanjutan muse hilang | engine berhenti di `message_done` pertama | ikuti `task.status` per sesi; sambung pesan lanjutan sampai task selesai (maks 180 dtk) | test_chat_files.py (fixture 06_csv) |
| F3 file .md tertukar dengan Blob pratinjau | memilih Blob "terbaru" | Blob dicocokkan lewat `<a download=nama>`; ukuran dicek terhadap `byte_len` | live uji 13 (sebelum: size 9373/10) |
| F4 .csv gagal "no-blob" | item Download belum aktif saat isi dimuat | satu percobaan ulang menu; error menyebut langkah yang gagal | live uji 15 |
| F5 tautan file tidak bisa diklik di /chat | md() hanya merender http(s) | `/v1/files/<32hex>.<ext>` → tombol unduh; pola lain tetap teks | test_chat_flows_browser (52/54 → 54/54) |

Keamanan `/v1/files`: selalu `attachment`, `application/octet-stream`, `nosniff`, `CSP: sandbox`; nama file divalidasi
regex `^[0-9a-f]{32}(\.[a-z0-9]{1,10})?$`; DELETE butuh API key. File HTML buatan muse tidak bisa berjalan di origin muse2api.
