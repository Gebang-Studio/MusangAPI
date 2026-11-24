# TEST_MATRIX — /chat (http://127.0.0.1:18610/chat)

Mulai 2026-11-24. Backup data: scratchpad/backup/chats.json (51.8K). Batas generate media: 3.
Status: ⏳ belum · ✅ lulus · ❌ bug (lihat Bug log) · ➖ dilewati (alasan)

| # | Kondisi | Status | Bukti / catatan |
|---|---------|--------|-----------------|
| 1 | Chat biasa, balasan stream | ❌→✅ | B1: pesan user tak tampil ~8 dtk selama /v1/intent |
| 2 | Balasan berisi kode + tabel + markdown panjang | ❌→✅ | B2: kata di sel tabel terpotong ("Pytho/n") |
| 3 | `/chat` paksa chat | ❌→✅ | B3: "/chat" ikut ke model & judul |
| 4 | `/gambar` generate gambar (media 1/3) | ✅ / ❌→✅ | Gambar jadi 33 dtk. B9: catatan "menyiapkan" tertinggal di samping error; B10: status "processing" bahasa Inggris |
| 5 | `/video` (media 2/3) | ✅ | 83 dtk, mp4 5 dtk 1280x720 terputar, label "Video · 5 dtk" |
| 6 | Kalimat ambigu ("gambarkan perasaanmu") → intent | ✅ / ❌→✅ | curl 8 frasa: semua masuk akal; B4: "/gambar" tanpa teks masuk antrean (202) |
| 7 | Input kosong / spasi saja | ✅ | 0 request terkirim |
| 8 | Input 10.000 karakter | ✅ | 9.972 char, jawaban benar "Apel, jeruk, mangga." |
| 9 | Emoji + unicode | ✅ | 👋🏽, bendera, "café" utuh |
| 10 | XSS: `<script>`, `<img onerror>`, link `javascript:` di input & di balasan | ✅ | 12 payload ke md(): 0 atribut on*/js:/data:, 0 script. Catatan: link markdown tidak dirender sama sekali |
| 11 | Server mati di tengah stream lalu hidup | ✅ (setelah B8) | kill -9 saat menunggu jawaban → pesan Indonesia + Coba lagi; setelah restart Coba lagi menjawab 3.797+ char |
| 12 | `chats.json` kosong / rusak (instance terpisah) | ❌→✅ | B6: file rusak -> GET [] -> PUT menimpa, isi hilang permanen |
| 13 | Dua tab mengedit bersamaan | ❌→✅ | B5: live terbukti — percakapan TAB-B hilang dari server setelah tab A kirim |
| 14 | `?key=` salah / tanpa key | ✅ | dialog key terbuka, key hilang dari URL, titik merah; push riwayat berhenti di GET 401 (tidak menimpa) |
| 15 | Reload di tengah jawaban | ❌→✅ | B7: reload 2 dtk setelah kirim → pesan user hilang total. Setelah fix: tersimpan + Coba lagi → "Merah, kuning, biru." |
| 16 | Mobile 375px | ✅ | Chrome minimal 500px live: overflow 0, tabel utuh; 375/390px diuji emulasi di test_chat_flows_browser |
| 17 | Memori 10 giliran | ✅ | chat_eval --memory: "Mochi, 3 tahun" sebelum & sesudah |
| 18 | API: PUT/GET /v1/chats tanpa key, body rusak, besar | ✅ / ➖ | 401 tanpa key, 422 bukan list (test_chats_sync). Ukuran besar ➖: server lokal tanpa batas body, bukan bug untuk pemakai tunggal |

## Baseline
- chat_eval sebelum: median intent 8.14s, kata pertama 12.29s, total 15.02s | format 16/20 | bahasa 15/20 | ingatan OK | error 0
- Tes yang ada: 8/9 skrip lulus; `test_composer_send_browser.py` gagal sebelum perubahan apa pun (tidak ada `chromium` di PATH macOS) → diberi fallback Chrome macOS seperti tes browser lain, sekarang lulus.

- chat_eval sesudah: median intent 8.48s, kata pertama 12.34s, total 14.24s | format 16/20 | bahasa 15/20 | ingatan OK | error 0 → setara (selisih = variasi muse). chat_eval memanggil API langsung, jadi tidak mengukur perbaikan UI; perbaikan UI dibuktikan oleh tes browser.
- Semua tes chat sesudah: 11/11 skrip lulus (test_chat_flows_browser 52/52; tiap cek baru gagal di chat.html lama: 45/52).
- data/chats.json: 3 percakapan dari backup utuh (isi pesan identik); 9 percakapan tambahan = percakapan uji.
- Gate UI (verify_states): 50 state elemen lulus WCAG AA.

## Bug log
| Bug | Penyebab | Perbaikan | Tes |
|-----|----------|-----------|-----|
| B1 pesan user & titik berpikir baru tampil setelah /v1/intent (~8 dtk) | `answer()` menunggu intent sebelum `render()` | render + placeholder berpikir di awal `answer()` | test_chat_flows_browser 2b (intent palsu 1,5 dtk) |
| B2 kata di sel tabel terpotong | `.bubble{overflow-wrap:anywhere}` diwarisi sel → lebar min kolom 1 huruf | `td,th{overflow-wrap:break-word}` | test_chat_flows_browser "sel tabel tidak memotong kata" |
| B3 "/chat" ikut ke model dan judul | client kirim teks mentah; server hanya membuang di intent | regex `CMD` (= `_OVERRIDE` intent.py) di judul & `streamChat` | test_chat_flows_browser "perintah /chat tidak ikut" |
| B4 "/gambar"/"/video" kosong → muse menggambar acak, kuota terbuang | 3 endpoint media tidak menolak prompt kosong tanpa acuan | `_require_prompt()` → 400 `prompt 为空`, diterjemahkan `friendly()` | tests/test_media_empty_prompt.py |
| B5 dua tab: tab lama menghapus percakapan tab lain | PUT menimpa seluruh daftar; tab hanya pull saat dimuat | `pushChats()` GET+merge sebelum PUT (synced/deleted), pull saat tab terlihat | tests/test_chats_two_tabs_browser.py |
| B6 chats.json rusak dihapus diam-diam | GET mengembalikan [] lalu PUT menimpa | file rusak dipindah ke `chats.json.corrupt-<ts>` + log | tests/test_chats_sync.py |
| B7 reload saat /v1/intent → pesan user hilang | pesan baru disimpan setelah intent menjawab | `persist()` saat kirim; saat dimuat, pesan user tanpa jawaban diberi "Terputus" + Coba lagi | test_chat_flows_browser 2c |
| B8 error jaringan tampil "network error"/"Failed to fetch" + bubble kosong | `TypeError` fetch diteruskan mentah; bubble kosong tetap punya padding | pesan Indonesia untuk `TypeError`; `.msg.assistant .bubble:empty{display:none}` | test_chat_flows_browser (fetch disimulasikan gagal) |
| B9 "Gambar · menyiapkan" tertinggal di samping error | catatan progres tidak di-reset saat gagal | catatan kembali ke label jenis (`m.spec`) di `answer()` & `resumeTask()` | test_chat_flows_browser "catatan progres tidak tertinggal" |
| B10 status "processing" bahasa Inggris saat membuat media | `tick(s.status)` menampilkan status mentah server | peta queued/processing/in_progress → antre/membuat | dicek live (sepele, tanpa tes) |
