"""Pemahaman narasi: kemiripan makna, pengelompokan narasi, frasa khas (sidik jari), sikap,
mutasi teks, lompatan platform, dan atribusi sumber per narasi."""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict

import networkx as nx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from scipy.sparse import hstack

from .textutil import STOPWORDS, URL_RE, MENTION_RE

# --------------------------------------------------------------------------- normalisasi bahasa Indonesia
SLANG = {
    "gak": "tidak", "ga": "tidak", "gk": "tidak", "nggak": "tidak", "enggak": "tidak", "tdk": "tidak", "ngga": "tidak",
    "yg": "yang", "dgn": "dengan", "utk": "untuk", "bgt": "banget", "udh": "sudah", "udah": "sudah", "sdh": "sudah",
    "blm": "belum", "jg": "juga", "sm": "sama", "krn": "karena", "karna": "karena", "dr": "dari", "aja": "saja",
    "gimana": "bagaimana", "hoax": "hoaks", "org": "orang", "tp": "tapi", "kalo": "kalau", "klo": "kalau",
    "bener": "benar", "lg": "lagi", "skrg": "sekarang", "pd": "pada", "dlm": "dalam", "bs": "bisa", "bkn": "bukan",
    "emg": "memang", "emang": "memang", "trs": "terus", "jd": "jadi", "sy": "saya", "gw": "saya", "gue": "saya",
    "aku": "saya", "lu": "kamu", "lo": "kamu", "pemkot": "pemerintah kota", "pemprov": "pemerintah provinsi",
    "pemda": "pemerintah daerah", "hati2": "hati hati", "ati2": "hati hati",
}
SUFFIX_RE = re.compile(r"(\w{3,}?)(nya|lah|kah|pun)\b")
NO_STRIP = {"setelah", "sebelah", "telah", "masalah", "sekolah", "salah", "kalah", "jumlah", "istilah", "olah",
            "langkah", "nikah", "ampun", "rumpun", "allah", "wilayah", "sumpah", "lelah", "pecah", "mudah", "sudah",
            "musibah", "ibadah", "sejarah", "daerah", "tanah", "rumah", "darah", "pemerintah", "nanah", "jarah",
            "parah", "ludah", "megah", "tengah", "bawah", "nasabah"}
REDUP_RE = re.compile(r"\b(\w+)2\b")            # anak2 -> anak anak
REDUP_DASH_RE = re.compile(r"\b(\w+)-\1\b")      # anak-anak -> anak


def normalize_id(text: str) -> str:
    t = (text or "").lower()
    t = URL_RE.sub(" ", t)
    t = MENTION_RE.sub(" ", t)
    t = t.replace("#", " ")
    t = REDUP_RE.sub(r"\1", t)
    t = REDUP_DASH_RE.sub(r"\1", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"(\w)\1{2,}", r"\1", t)
    words = []
    for w in t.split():
        w = SLANG.get(w, w)
        if w not in NO_STRIP:
            w = SUFFIX_RE.sub(r"\1", w)
        if len(w) > 1 and w not in STOPWORDS and not w.isdigit():
            words.append(w)
    return " ".join(words)


# --------------------------------------------------------------------------- sikap & gaya bahasa
STANCE_LEX = {
    "menyebarkan": ["sebarkan", "viralkan", "share", "bagikan", "waspada", "hati hati", "awas", "darurat", "usut",
                    "tuntas", "jangan diam", "bongkar", "terbukti", "fakta", "akhirnya terungkap"],
    "membantah": ["hoaks", "klarifikasi", "cek fakta", "cekfakta", "tidak benar", "bantah", "membantah",
                  "disinformasi", "misinformasi", "keliru", "menyesatkan", "turnbackhoax", "tidak terbukti", "aman"],
    "mempertanyakan": ["benarkah", "apa benar", "beneran", "serius", "masa sih", "hoaks tidak sih", "sumbernya",
                       "katanya", "kata siapa", "valid"],
}
URGENCY = ["darurat", "segera", "bahaya", "sebarkan", "viralkan", "waspada", "awas", "penting", "jangan sampai",
           "sebelum dihapus", "tolong", "mendesak"]


def stance_of(text: str) -> str:
    t = " " + normalize_id(text) + " "
    raw = (text or "").lower()
    scores = {k: sum(1 for w in v if f" {w} " in t or w in raw) for k, v in STANCE_LEX.items()}
    if raw.strip().endswith("?"):
        scores["mempertanyakan"] += 1
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else "netral"


def style_of(text: str) -> dict:
    raw = text or ""
    letters = [c for c in raw if c.isalpha()]
    caps = sum(c.isupper() for c in letters) / len(letters) if letters else 0
    low = raw.lower()
    return {"caps": round(caps, 2), "excl": raw.count("!"), "urgency": sum(w in low for w in URGENCY),
            "emoji": len(re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", raw))}


# --------------------------------------------------------------------------- indeks semantik
class SemanticIndex:
    """TF-IDF kata (1-2 gram) + karakter (3-5 gram) → kemiripan kosinus. Tahan terhadap typo, singkatan,
    imbuhan, dan parafrase ringan. Jika OSINT_EMBED_MODEL di-set dan sentence-transformers terpasang,
    embedding semantik multibahasa ikut digabungkan."""

    def __init__(self, ids, texts):
        self.ids = list(ids)
        self.norm = [normalize_id(t) for t in texts]
        self.ok = len(self.ids) >= 2 and any(self.norm)
        if not self.ok:
            return
        wv = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, min_df=1,
                             token_pattern=r"(?u)\b\w\w+\b")
        cv = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1, max_features=200000)
        Xw = wv.fit_transform(self.norm)
        Xc = cv.fit_transform(self.norm)
        self.word_vocab = np.array(wv.get_feature_names_out())
        self.Xw = Xw
        X = hstack([Xw * 0.55, Xc * 0.45]).tocsr()
        self.X = normalize(X)
        self.emb = None
        model_name = os.environ.get("OSINT_EMBED_MODEL")
        if model_name:
            try:
                from sentence_transformers import SentenceTransformer
                m = SentenceTransformer(model_name)
                self.emb = normalize(m.encode(texts, batch_size=64, show_progress_bar=False))
            except Exception as e:  # opsional
                from .log import log
                log(f"[narasi] embedding dilewati: {e}")

    def neighbors(self, threshold=0.3, chunk=400):
        """Kembalikan {i: {j: sim}} untuk pasangan dengan kemiripan >= threshold."""
        out = defaultdict(dict)
        if not self.ok:
            return out
        n = self.X.shape[0]
        XT = self.X.T.tocsc()
        for s in range(0, n, chunk):
            block = (self.X[s:s + chunk] @ XT).toarray()
            if self.emb is not None:
                block = 0.5 * block + 0.5 * (self.emb[s:s + chunk] @ self.emb.T)
            rows, cols = np.nonzero(block >= threshold)
            for r, c in zip(rows, cols):
                i = s + r
                if i != c:
                    out[self.ids[i]][self.ids[c]] = float(block[r, c])
        return out

    def key_terms(self, member_idx, k=10):
        """Istilah khas cluster (c-TF-IDF sederhana: rata-rata bobot di cluster / rata-rata global)."""
        if not self.ok or not member_idx:
            return []
        sub = np.asarray(self.Xw[member_idx].mean(axis=0)).ravel()
        glob = np.asarray(self.Xw.mean(axis=0)).ravel() + 1e-9
        score = sub * np.log1p(sub / glob)
        top = np.argsort(-score)[:k * 2]
        terms = []
        for t in top:
            term = self.word_vocab[t]
            if score[t] <= 0 or any(term in x or x in term for x in terms):
                continue
            terms.append(term)
            if len(terms) == k:
                break
        return terms


# --------------------------------------------------------------------------- frasa khas (sidik jari)
def signature_phrases(posts, global_df, n_min=3, n_max=5, min_posts=2, top=12):
    """N-gram (3-5 kata) yang dipakai berulang dalam satu narasi tapi jarang di luar narasi itu.
    Untuk tiap frasa: siapa yang pertama memakainya → petunjuk kuat sumber teks."""
    first, count, authors = {}, Counter(), defaultdict(set)
    for p in posts:  # posts terurut waktu
        toks = normalize_id(p.text).split()
        seen = set()
        for n in range(n_min, n_max + 1):
            for i in range(len(toks) - n + 1):
                g = " ".join(toks[i:i + n])
                if g in seen:
                    continue
                seen.add(g)
                count[g] += 1
                authors[g].add(p.author)
                first.setdefault(g, p)
    cand = []
    for g, c in count.items():
        if c < min_posts or len(authors[g]) < 2:
            continue
        outside = global_df.get(g, 0) - c
        spec = c / (c + outside)
        cand.append((c * spec * (1 + 0.15 * len(g.split())), g, c, spec))
    cand.sort(reverse=True)
    chosen = []
    for _, g, c, spec in cand:
        f = first[g]
        gw = set(g.split())
        if any(g in x["phrase"] or x["phrase"] in g or
               (x["first_id"] == f.id and x["posts"] == c and len(gw & set(x["phrase"].split())) >= 2)
               for x in chosen):
            continue  # potongan dari frasa yang sama
        chosen.append({"phrase": g, "posts": c, "authors": len(authors[g]), "specificity": round(spec, 2),
                       "first_author": f.author, "first_platform": f.platform, "first_id": f.id,
                       "first_time": f.created_at.isoformat()})
        if len(chosen) == top:
            break
    return chosen


def ngram_df(posts, n_min=3, n_max=5):
    df = Counter()
    for p in posts:
        toks = normalize_id(p.text).split()
        df.update({" ".join(toks[i:i + n]) for n in range(n_min, n_max + 1) for i in range(len(toks) - n + 1)})
    return df


# --------------------------------------------------------------------------- mutasi narasi
def mutations(variants, max_items=12):
    """Bandingkan tiap varian teks dengan varian pertama: kata apa yang ditambah / dihapus."""
    if not variants:
        return []
    base = set(normalize_id(variants[0]["text"]).split())
    out = []
    for v in variants[:max_items]:
        w = set(normalize_id(v["text"]).split())
        out.append({**v, "added": sorted(w - base)[:12], "removed": sorted(base - w)[:12]})
    return out


# --------------------------------------------------------------------------- bangun narasi
def build_narratives(posts, sem_nb, copy_group, parent, desc, feats, index: SemanticIndex,
                     cluster_threshold=0.35, min_size=3):
    """posts: terurut waktu. sem_nb: {id:{id:sim}}. copy_group: {id: group_root}."""
    by_id = {p.id: p for p in posts}
    order = {p.id: i for i, p in enumerate(posts)}
    G = nx.Graph()
    for a, nb in sem_nb.items():
        for b, s in nb.items():
            if s >= cluster_threshold and a < b:
                G.add_edge(a, b, weight=s)
    # salinan persis selalu satu narasi
    groups = defaultdict(list)
    for pid, g in copy_group.items():
        groups[g].append(pid)
    for mem in groups.values():
        for x in mem[1:]:
            G.add_edge(mem[0], x, weight=1.0)
    if G.number_of_nodes() == 0:
        return [], {}
    comms = nx.community.louvain_communities(G, weight="weight", resolution=1.0, seed=42)
    idx_of = {pid: i for i, pid in enumerate(index.ids)} if index.ok else {}
    all_sorted = posts
    global_df = ngram_df(all_sorted)
    narratives, post_narr = [], {}

    for comm in comms:
        core = sorted(comm, key=lambda x: order[x])
        if len(core) < min_size:
            continue
        mem = [by_id[x] for x in core]
        if len({m.parent_id for m in mem}) == 1 and mem[0].parent_id:
            continue  # hanya kumpulan komentar di bawah satu post, bukan narasi tersendiri
        # medoid = teks paling representatif
        def avg_sim(x):
            nb = sem_nb.get(x, {})
            return sum(nb.get(y, 0) for y in core) / max(1, len(core) - 1)
        medoid = max(core, key=avg_sim)
        # varian: satu perwakilan per kelompok salinan
        seen_g, variants = set(), []
        for m in mem:
            g = copy_group.get(m.id, m.id)
            if g in seen_g:
                continue
            seen_g.add(g)
            size = sum(1 for x in core if copy_group.get(x, x) == g)
            variants.append({"id": m.id, "author": m.author, "platform": m.platform,
                             "time": m.created_at.isoformat(), "text": m.text[:280], "copies": size})
        # lompatan platform
        jumps, seen_pl = [], {}
        t0 = mem[0].created_at
        for m in mem:
            if m.platform not in seen_pl:
                seen_pl[m.platform] = m
                jumps.append({"platform": m.platform, "author": m.author, "id": m.id, "time": m.created_at.isoformat(),
                              "delay_hours": round((m.created_at - t0).total_seconds() / 3600, 2),
                              "text": m.text[:160]})
        stances = Counter(stance_of(m.text) for m in mem)
        styles = [style_of(m.text) for m in mem]
        reactions = sum(desc.get(x, 0) for x in core)
        tags = Counter(t for m in mem for t in feats[m.id]["tags"])
        hourly = Counter(m.created_at.replace(minute=0, second=0, microsecond=0).isoformat() for m in mem)
        phrases = signature_phrases(mem, global_df)
        # atribusi sumber dalam narasi
        attrib = attribute_sources(mem, phrases, desc, parent, by_id)
        narratives.append({
            "id": "", "size": len(mem), "authors": len({m.author for m in mem}),
            "platforms": dict(Counter(m.platform for m in mem)),
            "first": _brief(mem[0]), "last_time": mem[-1].created_at.isoformat(),
            "duration_hours": round((mem[-1].created_at - t0).total_seconds() / 3600, 1),
            "representative": _brief(by_id[medoid], 400),
            "key_terms": index.key_terms([idx_of[x] for x in core if x in idx_of]),
            "hashtags": [t for t, _ in tags.most_common(8)],
            "stance": dict(stances), "dominant_stance": stances.most_common(1)[0][0],
            "style": {"avg_caps": round(sum(s["caps"] for s in styles) / len(styles), 2),
                      "urgency_posts": sum(1 for s in styles if s["urgency"] or s["excl"] >= 2),
                      "emoji_posts": sum(1 for s in styles if s["emoji"])},
            "variants": mutations(variants), "n_variants": len(variants),
            "platform_jumps": jumps, "signature_phrases": phrases, "reactions": reactions,
            "source_attribution": attrib, "hourly": sorted(hourly.items()), "ids": core,
        })
    narratives.sort(key=lambda n: -(n["size"] + n["reactions"] * 0.3))
    for i, n in enumerate(narratives):
        n["id"] = f"N{i + 1}"
        for x in n["ids"]:
            post_narr[x] = n["id"]
    return narratives, post_narr


def attribute_sources(mem, phrases, desc, parent, by_id, top=5):
    """Skor kandidat sumber per akun dalam satu narasi, beserta alasannya (bisa dijelaskan)."""
    t0 = mem[0].created_at
    span = max(1.0, (mem[-1].created_at - t0).total_seconds())
    acc = defaultdict(lambda: {"score": 0.0, "reasons": [], "first_time": None, "platform": "", "post_id": ""})
    for rank, m in enumerate(mem):
        a = acc[m.author]
        if a["first_time"] is None:
            a["first_time"], a["platform"], a["post_id"] = m.created_at.isoformat(), m.platform, m.id
            early = 1 - (m.created_at - t0).total_seconds() / span
            a["score"] += 3.0 * early ** 2 + (2.0 if rank == 0 else 0)
            if rank == 0:
                a["reasons"].append("post paling awal dalam narasi ini")
            elif rank < 3:
                a["reasons"].append(f"termasuk 3 post pertama (urutan ke-{rank + 1})")
        if m.id not in parent or by_id.get(parent[m.id]) is None:
            if desc.get(m.id, 0):
                a["score"] += min(4.0, 1.0 * np.log1p(desc[m.id]))
                a["reasons"].append(f"akar penyebaran: {desc[m.id]} post turunan")
    by_author = defaultdict(list)
    for ph in phrases:
        acc[ph["first_author"]]["score"] += 0.8 * ph["specificity"]
        by_author[ph["first_author"]].append(ph["phrase"])
    for author, phs in by_author.items():
        sample = ", ".join(f"\"{x}\"" for x in phs[:2])
        acc[author]["reasons"].append(f"pertama memakai {len(phs)} frasa khas ({sample}{', …' if len(phs) > 2 else ''})"
                                      if len(phs) > 1 else f"pertama memakai frasa khas {sample}")
    out = []
    for author, v in acc.items():
        if v["score"] <= 0.5:
            continue
        reasons = list(dict.fromkeys(v["reasons"]))
        out.append({"author": author, "score": round(v["score"], 2), "first_time": v["first_time"],
                    "platform": v["platform"], "post_id": v["post_id"], "reasons": reasons[:6]})
    out.sort(key=lambda x: -x["score"])
    tot = sum(x["score"] for x in out[:top]) or 1
    for x in out[:top]:
        x["share"] = round(x["score"] / tot, 2)
    return out[:top]


def _brief(p, n=220):
    return {"id": p.id, "platform": p.platform, "author": p.author, "kind": p.kind,
            "time": p.created_at.isoformat() if p.created_at else None, "url": p.url,
            "text": (p.text or "")[:n], "source": p.source, "engagement": p.engagement}


# --------------------------------------------------------------------------- jaringan akun
def account_network(posts, post_narr, window_min=30, min_shared=2):
    """Akun yang berulang kali memposting narasi yang sama dalam selang waktu dekat → kemungkinan satu
    jaringan (amplifikasi terorganisir / buzzer). Komunitas dicari dengan Louvain."""
    by_n = defaultdict(list)
    for p in posts:
        if p.id in post_narr and p.author:
            by_n[post_narr[p.id]].append(p)
    pair_w = Counter()
    pair_n = defaultdict(set)
    for nid, mem in by_n.items():
        mem.sort(key=lambda p: p.created_at)
        for i, a in enumerate(mem):
            for b in mem[i + 1:]:
                if (b.created_at - a.created_at).total_seconds() > window_min * 60:
                    break
                if a.author != b.author:
                    k = tuple(sorted((a.author, b.author)))
                    pair_w[k] += 1
                    pair_n[k].add(nid)
    G = nx.Graph()
    for (a, b), w in pair_w.items():
        if w >= min_shared or len(pair_n[(a, b)]) >= 2:
            G.add_edge(a, b, weight=w)
    if G.number_of_edges() == 0:
        return {"nodes": [], "edges": [], "communities": []}
    comms = [c for c in nx.community.louvain_communities(G, weight="weight", seed=42) if len(c) >= 3]
    comm_of = {a: i for i, c in enumerate(comms) for a in c}
    communities = []
    for i, c in enumerate(comms):
        sub = G.subgraph(c)
        nar = Counter(n for (a, b) in sub.edges() for n in pair_n[tuple(sorted((a, b)))])
        communities.append({"id": i, "size": len(c), "members": sorted(c),
                            "density": round(nx.density(sub), 2), "narratives": [n for n, _ in nar.most_common(5)],
                            "co_posts": int(sum(d["weight"] for _, _, d in sub.edges(data=True)))})
    communities.sort(key=lambda c: -c["co_posts"])
    return {"nodes": [{"id": a, "degree": G.degree(a), "community": comm_of.get(a, -1)} for a in G.nodes()],
            "edges": [{"from": a, "to": b, "weight": d["weight"]} for a, b, d in G.edges(data=True)],
            "communities": communities}
