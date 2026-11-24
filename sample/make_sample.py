"""Data FIKTIF untuk demo: isu "air kota tercemar" di kota rekaan Lembahsari."""
import random
from datetime import datetime, timedelta, timezone

from tracer.models import Post

WIB = timezone(timedelta(hours=7))


def make(seed=7):
    rnd = random.Random(seed)
    t0 = datetime(2026, 11, 10, 21, 14, tzinfo=WIB)
    P = []

    new_accounts = {}

    def add(plat, author, text, dt, kind="post", parent="", url="", source="", eng=0):
        pid = f"{plat}:{len(P) + 1000}"
        extra = {"author_created": new_accounts[author]} if author in new_accounts else {}
        P.append(Post(id=pid, platform=plat, author=author, text=text, created_at=dt, kind=kind,
                      parent_id=parent, url=url or f"https://example.org/{plat}/{len(P) + 1000}", source=source,
                      engagement=eng, extra=extra))
        return pid

    seed_txt = ("Hati-hati warga Lembahsari, air PDAM hari ini bau kimia, anak tetangga saya muntah muntah "
                "setelah minum. Katanya ada limbah pabrik dibuang ke sumber air. Sebarkan!")
    root = add("facebook", "warga_lembah88", seed_txt, t0, eng=340)
    for i, a in enumerate(["ibu_rina_ls", "pakdhe_somad", "lembahsari_info"]):
        add("facebook", a, "Bener ini? di rumah saya juga bau", t0 + timedelta(minutes=12 + i * 7), "comment", root)

    # disalin ke X beberapa puluh menit kemudian
    x1 = add("x", "kabar_lembah", "Hati2 warga Lembahsari air PDAM hari ini bau kimia, anak tetangga muntah muntah "
             "setelah minum. Katanya ada limbah pabrik dibuang ke sumber air. Sebarkan!", t0 + timedelta(minutes=41), eng=900)
    for i, a in enumerate(["dodi_ptr", "sari_n", "rakyat_jelata21"]):
        add("x", a, "", t0 + timedelta(minutes=50 + i * 9), "repost", x1)
    add("x", "netizen_kritis", "Kalau benar ini parah sih, PDAM harus jelasin", t0 + timedelta(minutes=70), "quote", x1)

    # pagi: banyak akun dengan narasi hampir identik + hashtag dalam jendela singkat
    t1 = datetime(2026, 11, 11, 7, 0, tzinfo=WIB)
    buzz = ["suara_lembah01", "garda_warga_ls", "info_terkini_99", "akunbaru_7731", "patriot_lembah",
            "realfakta_id", "warga_peduli_x"]
    for i, a in enumerate(buzz):
        new_accounts[a] = (t0 - timedelta(days=3 + i)).isoformat()
    for i, a in enumerate(buzz):
        tail = rnd.choice(["Usut tuntas!", "Pemerintah diam saja?", "Jangan diam!", "Viralkan!"])
        add("x", a, "Air PDAM Lembahsari tercemar limbah pabrik, anak anak muntah setelah minum. "
            f"Pemkot tutup mata! {tail} #AirKotaTercemar #LembahsariDarurat",
            t1 + timedelta(minutes=i * 1.3 + rnd.random()), eng=rnd.randint(20, 300))

    tk = add("tiktok", "lembahsari.viral", "air PDAM bau kimia, katanya limbah pabrik 😭 anak2 muntah "
             "#AirKotaTercemar #LembahsariDarurat #fyp #viral", t1 + timedelta(hours=2, minutes=30), eng=48000)
    for i in range(6):
        add("tiktok", f"user{rnd.randint(1000, 9999)}", rnd.choice(["sama di rumahku jg bau", "serem bgt",
            "hoax ga sih?", "PDAM jawab dong", "aku udh beli galon"]), t1 + timedelta(hours=2, minutes=40 + i * 6),
            "comment", tk)
    ig = add("instagram", "lembahsari_update", "BEREDAR: warga mengeluhkan air PDAM bau kimia dan diduga tercemar "
             "limbah pabrik. Benarkah? #AirKotaTercemar #infolembahsari", t1 + timedelta(hours=3), eng=5200)
    add("instagram", "mama_kevin", "ya ampun anakku tadi juga mual", t1 + timedelta(hours=3, minutes=5), "comment", ig)

    # berita
    news_url = "https://berita-contoh.id/regional/viral-air-pdam-lembahsari-tercemar-ini-kata-pdam"
    add("news", "berita-contoh.id", "Viral Isu Air PDAM Lembahsari Tercemar Limbah Pabrik, Ini Kata PDAM",
        t1 + timedelta(hours=5), "article", url=news_url, source="berita-contoh.id")
    add("news", "kabarkota.example", "PDAM Lembahsari: Air Aman, Bau Akibat Pembersihan Pipa",
        t1 + timedelta(hours=7), "article", url="https://kabarkota.example/pdam-air-aman", source="kabarkota.example")
    for i, a in enumerate(["jurnalis_lokal", "dodi_ptr", "warga_peduli_x"]):
        add("x", a, rnd.choice(["Akhirnya ada tanggapan", "Nah ini", "Baca dulu"]) + " " + news_url + "?utm_source=x",
            t1 + timedelta(hours=5, minutes=20 + i * 15))

    # kontra-narasi
    t2 = t1 + timedelta(hours=8)
    for i, a in enumerate(["cek_fakta_ls", "pemkot_lembahsari", "relawan_air", "dr_anisa"]):
        add("x", a, "Klarifikasi: PDAM Lembahsari menyatakan air aman diminum, bau berasal dari pembersihan pipa. "
            "Isu limbah pabrik tidak terbukti #CekFakta #AirKotaTercemar", t2 + timedelta(minutes=i * 25))

    # narasi turunan: jaringan akun yang sama mendorong tuntutan baru (parafrase, bukan salinan)
    t3 = t1 + timedelta(days=1, hours=1)
    demands = ["Pabrik kimia di hulu Lembahsari harus ditutup sekarang juga, sudah meracuni air warga! #TutupPabrikLimbah",
               "Tutup pabrik kimia yang meracuni air PDAM Lembahsari! Warga jadi korban #TutupPabrikLimbah",
               "Sudah jelas pabrik kimia hulu meracuni air warga Lembahsari, tutup sekarang #TutupPabrikLimbah",
               "Warga Lembahsari korban air beracun pabrik kimia. Tutup pabriknya! #TutupPabrikLimbah",
               "Pabrik kimia peracun air Lembahsari wajib ditutup #TutupPabrikLimbah #LembahsariDarurat"]
    for i, a in enumerate(buzz[:5]):
        add("x", a, demands[i], t3 + timedelta(minutes=i * 3 + rnd.random()), eng=rnd.randint(10, 90))
    add("tiktok", "lembahsari.viral", "pabrik kimia ini katanya yg bikin air beracun, harus ditutup? #TutupPabrikLimbah",
        t3 + timedelta(hours=2), eng=12000)

    # noise
    noise = ["Macet parah di jalan utama Lembahsari pagi ini", "Kuliner enak di Lembahsari apa ya?",
             "Hujan deras sore ini #Lembahsari", "Konser minggu depan jadi ga?", "Ada yang tau bengkel dekat alun2?",
             "Selamat pagi Lembahsari #Lembahsari"]
    for i, txt in enumerate(noise):
        add(rnd.choice(["x", "instagram"]), f"random_{i}", txt, t0 + timedelta(hours=rnd.randint(-10, 30)))
    return P
