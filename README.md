# OSINT Issue Tracer

Aplikasi web untuk menelusuri **dari mana sebuah isu berasal dan bagaimana ia menyebar**. Tool ini memetakan
hashtag, komentar, caption, dan berita dari berbagai platform, mengelompokkan narasi yang mirip maknanya, lalu
menunjukkan kandidat sumber beserta alasannya.

## Menjalankan
```bash
./run.sh            # Linux/macOS  (Windows: run.bat)
```
atau manual:
```bash
pip install -r requirements.txt
python app.py
```
Buka **http://127.0.0.1:5000**, lalu klik **"Coba dengan data demo"** untuk melihat semua fitur dengan data fiktif.

Server hanya bisa diakses dari komputer sendiri. Untuk dibuka dari perangkat lain di jaringan yang sama:
`python app.py --host 0.0.0.0 --port 8080`. Aplikasi ini tidak punya login, jadi jangan dibuka ke internet.

## Alur kerja
1. **Kasus baru** → beri nama isu yang diteliti.
2. **Tab Data** → kumpulkan otomatis dan/atau unggah file:
   - Otomatis: Google News, GDELT, X, TikTok, Reddit, Mastodon, Bluesky.
   - Unggah CSV/JSON/JSONL dari platform apa pun (Instagram, Facebook, YouTube, WhatsApp/Telegram yang disalin
     ke spreadsheet, dll). Kolom teks, waktu, dan akun dikenali otomatis. Format X API v2, Apify, dan TikTok Research
     dikenali langsung, dan platform ditebak dari nama kolom/URL.
3. **Analisis** → atur ambang bila perlu, dan aktifkan ringkasan Claude (opsional).
4. Telusuri hasilnya di tab berikut:

| Tab | Isi |
|---|---|
| Ringkasan | Kandidat sumber + alasannya, kemunculan pertama per platform, volume per jam, sikap, penilaian Claude |
| Narasi | Klaim inti, istilah kunci, **kemungkinan sumber** (skor + alasan), **lompatan antar platform**, **frasa khas (sidik jari)**, **mutasi teks**, pola koordinasi |
| Graf penyebaran | Siapa menyebarkan dari siapa: sumbu waktu, satu jalur per cascade, filter per narasi |
| Jaringan & koordinasi | Kelompok akun yang berulang kali memposting narasi sama secara berdekatan, dan ledakan posting serentak |
| Hashtag | Pemakai pertama, 5 akun pertama, jam puncak, narasi terkait |
| Akun | Jangkauan, pengaruh, narasi, sikap, dan catatan (akun baru, ikut koordinasi, pemula narasi, dll) |

Ekspor: CSV (post, sumber, narasi, akun, hashtag, tautan), GEXF untuk Gephi, dan JSON lengkap.

## Cara tool memahami pola narasi
- **Kemiripan makna**: TF-IDF kata (1–2 gram) digabung n-gram karakter (3–5) atas teks yang sudah dinormalisasi:
  slang (`yg`, `gak`, `bgt`, …), reduplikasi (`anak2`), akhiran (`-nya`, `-lah`), dan kata umum dibuang.
  Hasilnya tahan terhadap typo, singkatan, dan parafrase ringan. Opsional: set `OSINT_EMBED_MODEL`
  (mis. `paraphrase-multilingual-MiniLM-L12-v2`) dan pasang `sentence-transformers` agar embedding semantik ikut dipakai.
- **Narasi**: komunitas Louvain di graf kemiripan, ditambah salinan persis (MinHash).
- **Induk tiap post** (dari yang paling pasti): reply/repost/quote/komentar → salin teks → link sama →
  narasi mirip → hashtag spesifik yang sama.
- **Frasa khas**: rangkaian 3–5 kata yang berulang di satu narasi tapi jarang di luar narasi itu. Siapa yang pertama
  memakainya adalah petunjuk kuat asal teks, termasuk saat teks dibingkai ulang oleh akun lain.
- **Atribusi sumber per narasi**: skor gabungan dari seberapa awal, jumlah post turunan, dan kepemilikan frasa khas.
- **Mutasi**: tiap varian teks dibandingkan dengan varian pertama (kata yang ditambah atau hilang).
- **Lompatan platform**: urutan dan jeda munculnya narasi di tiap platform.
- **Sikap**: menyebarkan / mempertanyakan / membantah / netral (berbasis leksikon). Ditambah gaya: ajakan, huruf kapital, emoji.
- **Koordinasi**: ≥ N akun berbeda memposting narasi yang sama dalam M menit.
  **Jaringan akun**: akun yang berulang kali berdekatan di narasi yang sama (Louvain).
- **Claude (opsional)**: membaca sampel tiap narasi dan bukti yang sudah dihitung, lalu menulis klaim inti, framing,
  sinyal manipulasi, evolusi teks, penilaian sumber, dan langkah verifikasi. Angka dan atribusi tetap dihitung
  secara deterministik; Claude hanya menafsirkan. Isi post diperlakukan sebagai data, bukan instruksi.

## Token & pengaturan
Isi di menu **Pengaturan & token** (disimpan di `data/settings.json` lokal) atau lewat variabel lingkungan:

| Variabel | Untuk |
|---|---|
| `ANTHROPIC_API_KEY` | Ringkasan narasi oleh Claude (model default `claude-opus-5-5`, ganti dengan `OSINT_CLAUDE_MODEL`) |
| `X_BEARER_TOKEN` | X API v2 (Basic: 7 hari, Pro: arsip penuh) |
| `APIFY_TOKEN` | Alternatif X & TikTok (`apidojo/tweet-scraper`, `clockworks/tiktok-scraper`, `clockworks/tiktok-comments-scraper`) |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | TikTok Research API (khusus peneliti yang disetujui) |
| `BSKY_HANDLE`, `BSKY_APP_PASSWORD` | Bluesky |
| `CAMOUFOX_PROXY` | Proxy untuk browser Camoufox (`http://user:pass@host:port` / `socks5://host:port`) |

Data kasus tersimpan di `data/osint.db` (SQLite). Untuk memindah lokasinya, set `OSINT_DATA_DIR`.

## TikTok lewat browser (Camoufox)
Untuk mengambil video TikTok (hashtag, hasil pencarian, URL tertentu) beserta komentar dan balasannya tanpa API resmi
atau Apify.

**Pasang sekali:**
```bash
pip install camoufox
python -m camoufox fetch     # mengunduh browser Camoufox (±100–200 MB)
```

**Pakai di aplikasi web:**
1. **Pengaturan → Camoufox**: isi **Proxy** (opsional, disarankan), mis. `http://user:pass@host:port` atau
   `socks5://host:port`, lalu klik **Tes proxy**. Hasilnya menunjukkan IP yang terlihat oleh situs dan apakah IP asli
   Anda tersembunyi. Proxy SOCKS5 dengan username/password didukung: karena browser Firefox/Camoufox tidak bisa
   memakainya langsung, aplikasi otomatis menjalankan jembatan lokal di `127.0.0.1` yang meneruskan koneksi ke proxy
   Anda (DNS juga di-resolve lewat proxy).
2. Klik **Buka browser untuk login / verifikasi** → login ke TikTok dengan akun Anda (sebaiknya akun terpisah), lalu
   tutup jendelanya. Sesi tersimpan di `data/camoufox_profile`. Langkah ini hanya bisa dilakukan bila aplikasi berjalan
   di komputer Anda sendiri, karena jendela browser perlu tampil.
3. **Tab Data → TikTok lewat browser**: isi **Daftar target**, satu per baris, lalu **Mulai kumpulkan**:
   ```
   #airkotatercemar | 200                                   ← video dari hashtag (maks 200)
   @lembahsari.viral                                        ← video dari profil akun
   dasco calon wakil presiden                               ← pencarian TikTok
   https://www.tiktok.com/@akun/video/7311234567890123456 | 500   ← komentar video itu (maks 500)
   ```
   URL hashtag (`/tag/…`), pencarian (`/search?q=…`), dan profil (`/@akun`) juga dikenali. `| angka` = batas per
   target. Komentar dari N video teratas bisa diambil otomatis, dan balasan komentar bisa dibuka.

**Pola pemuatan:** item terakhir di daftar (hasil video atau komentar) digulir ke tengah layar
(`scrollIntoView`), lalu menunggu ikon loading hilang sebelum lanjut. Ini pola yang sama seperti pengguna menggulir,
dan lebih andal daripada roda mouse untuk daftar TikTok yang hanya memuat item saat terlihat. Halaman
"Something went wrong" terdeteksi: tombol *Try again* diklik sekali, dan bila masih gagal, log menjelaskannya.

**Cara kerja:** browser membuka halaman TikTok seperti pengguna biasa, lalu membaca data JSON yang dimuat halaman itu
sendiri (daftar video hashtag/pencarian, detail video, daftar komentar dan balasan). Jeda acak 2–5 detik antar langkah,
dengan batas jumlah video dan komentar. Bila TikTok meminta verifikasi (CAPTCHA), proses **berhenti**, data yang sudah
tertangkap tetap disimpan, dan Anda diminta menyelesaikan verifikasi secara manual lewat tombol login. Tool ini tidak
mencoba membobol verifikasi dan tidak merotasi proxy/identitas.

**Bila pencarian/hashtag menghasilkan 0 video**, log job menjelaskan penyebabnya:
- *"TikTok mengalihkan halaman"* atau *"menampilkan jendela login"* → TikTok mewajibkan login untuk pencarian. Klik
  **Buka browser untuk login / verifikasi**, login, tutup jendelanya, lalu jalankan lagi.
- *"API … status_code=… / butuh verifikasi"* → TikTok menolak permintaan; selesaikan verifikasi lewat tombol yang sama.
- Screenshot dan HTML halaman disimpan di `data/debug/` supaya Anda bisa melihat apa yang ditampilkan TikTok.
- Bila data API tidak tertangkap tetapi video tampil di layar, video diambil dari kartu hasil di halaman (waktu unggah
  dihitung dari ID video).
- Hanya satu browser Camoufox boleh berjalan pada satu waktu. Tutup jendela login sebelum mengumpulkan data.

**Catatan:** scraping melanggar ketentuan layanan TikTok, jadi akun yang dipakai bisa dibatasi. Tampilan dan format data
TikTok sering berubah. Bila hasilnya kosong, kemungkinan pola URL API di `tracer/tiktok_browser.py` (`API_PATTERNS`)
perlu diperbarui.

## CLI (untuk otomasi/terjadwal)
```bash
python trace.py collect --x '#AirKotaTercemar lang:id' --gnews "air pdam tercemar" -o data/raw.jsonl --append
python trace.py analyze -i data/raw.jsonl -o out/ [--llm]
```

## Uji
```bash
python -m tests.test_x_tiktok   # parser & kolektor X/TikTok (respons tiruan)
python -m tests.test_llm        # jalur Claude (klien tiruan)
python -m tests.test_tiktok_browser   # kolektor Camoufox vs situs TikTok tiruan lokal (pakai Chromium Playwright)
python -m tests.test_proxy_bridge     # jembatan proxy SOCKS5 dengan login
```

## Keterbatasan (penting)
- "Paling awal" artinya paling awal **di data yang terkumpul**. Post yang dihapus, akun privat, grup tertutup
  (WhatsApp/Telegram/FB Group), dan batas API bisa menyembunyikan sumber sebenarnya.
- Tautan selain balasan/repost/quote, sinyal koordinasi, dan jaringan akun adalah **indikasi**, bukan bukti.
- Ambang kemiripan perlu disesuaikan dengan ukuran data: korpus kecil menghasilkan skor kemiripan lebih rendah.
- Isu yang berawal dari gambar/video perlu ditelusuri juga lewat reverse image search, InVID/WeVerify, Wayback Machine,
  dan archive.today.
- Gunakan sesuai hukum & ketentuan platform (UU ITE, UU PDP). Hindari membeberkan data pribadi orang biasa.
