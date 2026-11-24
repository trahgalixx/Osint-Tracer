"""Analisis: pohon penyebaran, narasi (kemiripan makna), hashtag, akun, jaringan, dan sinyal koordinasi."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

import networkx as nx

from .log import log
from .narrative import SemanticIndex, account_network, build_narratives, stance_of
from .textutil import (MinHashLSH, extract_hashtags, extract_mentions, extract_urls, jaccard, norm_url,
                       shingles, tokens)

GENERIC_TAGS = {"fyp", "fypシ", "fy", "foryou", "foryoupage", "viral", "trending", "xyzbca", "explore", "news",
                "berita", "beritaterkini", "infoterkini", "repost", "reels", "shorts", "tiktok", "instagram"}

DEFAULTS = {
    "copy_threshold": 0.5,       # Jaccard 3-kata: dianggap salinan
    "link_threshold": 0.25,      # kemiripan makna: dianggap menyebarkan narasi dari post sebelumnya
    "cluster_threshold": 0.25,   # kemiripan makna: masuk narasi yang sama
    "min_narrative": 3,
    "coord_window_min": 10,
    "coord_min_accounts": 4,
    "network_window_min": 30,
    "keyword_filter": None,
}


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra > rb:
                ra, rb = rb, ra
            self.p[rb] = ra


def _pagerank(G, alpha=0.85, iters=100):
    n = G.number_of_nodes()
    if not n:
        return {}
    r = {v: 1 / n for v in G}
    out_w = {v: sum(d.get("weight", 1) for _, _, d in G.out_edges(v, data=True)) for v in G}
    for _ in range(iters):
        dangling = alpha * sum(r[v] for v in G if out_w[v] == 0) / n
        new = {v: (1 - alpha) / n + dangling for v in G}
        for u, v, d in G.edges(data=True):
            new[v] += alpha * r[u] * d.get("weight", 1) / out_w[u]
        done = sum(abs(new[v] - r[v]) for v in G) < 1e-9
        r = new
        if done:
            break
    return r


def _brief(p, n=220):
    return {"id": p.id, "platform": p.platform, "author": p.author, "kind": p.kind,
            "time": p.created_at.isoformat() if p.created_at else None, "url": p.url,
            "text": (p.text or "")[:n], "source": p.source, "engagement": p.engagement}


def analyze(posts, **params):
    P = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    # ---------- 1. bersihkan
    seen, clean = set(), []
    kw = [k.lower() for k in P["keyword_filter"] or []]
    for p in posts:
        if p.id in seen or p.created_at is None:
            continue
        if kw and not any(k in (p.text or "").lower() for k in kw) and not p.parent_id:
            continue
        seen.add(p.id)
        clean.append(p)
    posts = sorted(clean, key=lambda p: (p.created_at, p.id))
    if not posts:
        return {"summary": {"posts": 0, "authors": 0, "platforms": {}, "first_seen": None, "last_seen": None,
                            "first_by_platform": {}, "edges_by_reason": {}, "narratives": 0, "hashtags": 0,
                            "coordination_flags": 0},
                "origin_candidates": [], "narratives": [], "hashtags": [], "accounts": [], "coordination": [],
                "account_network": {"nodes": [], "edges": [], "communities": []}, "timeline": [],
                "graph": {"nodes": [], "edges": []}, "params": P}
    order = {p.id: i for i, p in enumerate(posts)}
    by_id = {p.id: p for p in posts}
    log(f"[analisis] {len(posts)} post")

    feats, lsh = {}, MinHashLSH()
    for p in posts:
        sh = shingles(tokens(p.text))
        urls = set(extract_urls(p.text))
        if p.url and p.platform == "news":
            urls.add(norm_url(p.url))
        if p.extra.get("link"):
            urls.add(norm_url(p.extra["link"]))
        feats[p.id] = {"sh": sh, "tags": extract_hashtags(p.text), "mentions": extract_mentions(p.text), "urls": urls}
        if len(sh) >= 2:
            lsh.add(p.id, sh)

    # ---------- 2. salinan persis (MinHash) → kelompok salinan
    copy_nb = defaultdict(dict)
    uf = UF()
    for a, b in lsh.candidate_pairs():
        j = jaccard(feats[a]["sh"], feats[b]["sh"])
        if j >= P["copy_threshold"]:
            copy_nb[a][b] = copy_nb[b][a] = j
            uf.union(a, b)
    copy_group = {pid: uf.find(pid) for pid in copy_nb}

    # ---------- 3. kemiripan makna (TF-IDF kata + karakter)
    sem_posts = [p for p in posts if len((p.text or "").split()) >= 4 and p.kind != "repost"]
    index = SemanticIndex([p.id for p in sem_posts], [p.text for p in sem_posts])
    sem_nb = index.neighbors(threshold=min(P["cluster_threshold"], P["link_threshold"]))
    log(f"[analisis] {sum(len(v) for v in sem_nb.values()) // 2} pasangan teks bermakna mirip")

    # ---------- 4. inferensi induk
    url_first, tag_first = {}, {}
    tag_count = Counter(t for f in feats.values() for t in f["tags"])
    parent, reason, conf = {}, {}, {}
    for p in posts:
        f = feats[p.id]
        if p.parent_id and p.parent_id in by_id and by_id[p.parent_id].created_at <= p.created_at:
            parent[p.id], reason[p.id], conf[p.id] = p.parent_id, p.kind if p.kind != "post" else "reply", 1.0
        else:
            earlier = [(j, q) for q, j in copy_nb[p.id].items() if order[q] < order[p.id]]
            if earlier:
                j, q = max(earlier, key=lambda t: (round(t[0], 2), -order[t[1]]))
                parent[p.id], reason[p.id], conf[p.id] = q, "copy-text", round(j, 2)
            else:
                shared = [url_first[u] for u in f["urls"] if u in url_first]
                if shared:
                    q = min(shared, key=lambda x: order[x])
                    parent[p.id], reason[p.id], conf[p.id] = q, "shared-url", 0.7
                else:
                    earlier = [(s, q) for q, s in sem_nb.get(p.id, {}).items()
                               if order[q] < order[p.id] and s >= P["link_threshold"]]
                    if earlier:
                        s, q = max(earlier, key=lambda t: (round(t[0], 2), -order[t[1]]))
                        parent[p.id], reason[p.id], conf[p.id] = q, "similar-narrative", round(s, 2)
                    else:
                        specific = [t for t in f["tags"] if t in tag_first and t not in GENERIC_TAGS]
                        if specific:
                            t = min(specific, key=lambda t: tag_count[t])
                            parent[p.id], reason[p.id], conf[p.id] = tag_first[t], "shared-hashtag", 0.3
        for u in f["urls"]:
            url_first.setdefault(u, p.id)
        for t in f["tags"]:
            tag_first.setdefault(t, p.id)

    children = defaultdict(list)
    for c, par in parent.items():
        children[par].append(c)
    desc = {}
    for p in reversed(posts):
        desc[p.id] = sum(1 + desc[c] for c in children[p.id])

    def root_of(pid):
        hops = 0
        while pid in parent and hops < 100000:
            pid, hops = parent[pid], hops + 1
        return pid

    # ---------- 5. narasi
    narratives, post_narr = build_narratives(posts, sem_nb, copy_group, parent, desc, feats, index,
                                             cluster_threshold=P["cluster_threshold"], min_size=P["min_narrative"])
    log(f"[analisis] {len(narratives)} narasi")

    # ---------- 6. kandidat sumber (akar cascade)
    t0 = posts[0].created_at
    cascade = defaultdict(list)
    for p in posts:
        cascade[root_of(p.id)].append(p)
    origin = []
    for r in (p for p in posts if p.id not in parent):
        mem = cascade[r.id]
        plats = Counter(m.platform for m in mem)
        hrs = (r.created_at - t0).total_seconds() / 3600
        score = (desc[r.id] + 1) * (1 + 0.5 * (len(plats) - 1)) / (1 + hrs / 24) ** 0.5
        reasons = []
        if desc[r.id]:
            reasons.append(f"akar dari {desc[r.id]} post turunan")
        if len(plats) > 1:
            reasons.append(f"menyebar ke {len(plats)} platform")
        if r.id == posts[0].id:
            reasons.append("post paling awal di seluruh data")
        nid = post_narr.get(r.id)
        if nid:
            n = next(x for x in narratives if x["id"] == nid)
            if n["first"]["id"] == r.id:
                reasons.append(f"post pertama narasi {nid}")
        origin.append({**_brief(r), "cascade_size": desc[r.id] + 1, "platforms": dict(plats),
                       "unique_authors": len({m.author for m in mem}),
                       "span_hours": round((mem[-1].created_at - r.created_at).total_seconds() / 3600, 1),
                       "hours_after_first_seen": round(hrs, 1), "score": round(score, 2),
                       "narrative": nid, "reasons": reasons})
    origin.sort(key=lambda o: -o["score"])

    # ---------- 7. hashtag
    tag_posts, co = defaultdict(list), Counter()
    for p in posts:
        tags = feats[p.id]["tags"]
        for t in tags:
            tag_posts[t].append(p)
        for i in range(len(tags)):
            for j in range(i + 1, len(tags)):
                co[(tags[i], tags[j])] += 1
    hashtags = []
    for t, ps in tag_posts.items():
        hourly = Counter(p.created_at.replace(minute=0, second=0, microsecond=0) for p in ps)
        peak = max(hourly.items(), key=lambda kv: kv[1])
        firsts, fa = [], set()
        for p in ps:
            if p.author not in fa:
                fa.add(p.author)
                firsts.append(_brief(p, 140))
            if len(firsts) == 5:
                break
        hashtags.append({"tag": t, "count": len(ps), "authors": len({p.author for p in ps}),
                         "platforms": dict(Counter(p.platform for p in ps)), "first": firsts[0],
                         "first_authors": firsts, "peak_hour": peak[0].isoformat(), "peak_count": peak[1],
                         "generic": t in GENERIC_TAGS,
                         "narratives": [n for n, _ in Counter(post_narr[p.id] for p in ps if p.id in post_narr).most_common(3)],
                         "co_tags": [a if b == t else b for (a, b), _ in co.most_common() if t in (a, b)][:6]})
    hashtags.sort(key=lambda h: -h["count"])

    # ---------- 8. koordinasi (dalam tiap narasi)
    coord = []
    win = timedelta(minutes=P["coord_window_min"])
    for n in narratives:
        mem = [by_id[i] for i in n["ids"]]
        lo, best = 0, None
        for hi in range(len(mem)):
            while mem[hi].created_at - mem[lo].created_at > win:
                lo += 1
            k = len({m.author for m in mem[lo:hi + 1]})
            if k >= P["coord_min_accounts"] and (best is None or k > best[2]):
                best = (lo, hi, k)
        if best:
            w = mem[best[0]:best[1] + 1]
            same_text = len({copy_group.get(m.id, m.id) for m in w})
            tagsets = Counter(tuple(feats[m.id]["tags"]) for m in w)
            coord.append({"narrative": n["id"], "narrative_first": n["first"]["text"][:140],
                          "accounts": sorted({m.author for m in w}), "n_accounts": best[2],
                          "start": w[0].created_at.isoformat(), "end": w[-1].created_at.isoformat(),
                          "minutes": round((w[-1].created_at - w[0].created_at).total_seconds() / 60, 1),
                          "platforms": dict(Counter(m.platform for m in w)),
                          "text_variants": same_text, "identical_hashtag_sets": tagsets.most_common(1)[0][1],
                          "ids": [m.id for m in w]})
    coord.sort(key=lambda c: -c["n_accounts"])

    # ---------- 9. jaringan akun
    net = account_network(posts, post_narr, window_min=P["network_window_min"])

    # ---------- 10. akun
    G = nx.DiGraph()
    for c, par in parent.items():
        a, b = by_id[par].author, by_id[c].author
        if a and b and a != b:
            w = G.get_edge_data(b, a, {}).get("weight", 0)
            G.add_edge(b, a, weight=w + 1)
    pr = _pagerank(G)
    comm_of = {m: c["id"] for c in net["communities"] for m in c["members"]}
    coord_accounts = Counter(a for c in coord for a in c["accounts"])
    first_of_narr = Counter(n["first"]["author"] for n in narratives)
    phrase_first = Counter(f["first_author"] for n in narratives for f in n["signature_phrases"])
    acc = defaultdict(lambda: {"posts": 0, "first_post": None, "platforms": set(), "copied_by": set(),
                               "first_mover_tags": [], "roots": 0, "reach": 0, "narratives": set(),
                               "stances": Counter(), "created": None, "followers": None})
    for p in posts:
        a = acc[p.author]
        a["posts"] += 1
        a["platforms"].add(p.platform)
        a["first_post"] = a["first_post"] or p.created_at.isoformat()
        a["stances"][stance_of(p.text)] += 1
        a["created"] = a["created"] or p.extra.get("author_created")
        a["followers"] = a["followers"] or p.extra.get("author_followers")
        if p.id in post_narr:
            a["narratives"].add(post_narr[p.id])
        if p.id not in parent:
            a["roots"] += 1
            a["reach"] += desc[p.id]
    for c, par in parent.items():
        if by_id[par].author != by_id[c].author:
            acc[by_id[par].author]["copied_by"].add(by_id[c].author)
    for h in hashtags:
        if not h["generic"]:
            for f in h["first_authors"][:3]:
                acc[f["author"]]["first_mover_tags"].append(h["tag"])
    accounts = []
    for k, v in acc.items():
        if not k:
            continue
        flags = []
        if coord_accounts[k]:
            flags.append(f"ikut {coord_accounts[k]}x pola koordinasi")
        if k in comm_of:
            flags.append(f"anggota jaringan #{comm_of[k] + 1}")
        if first_of_narr[k]:
            flags.append(f"pemula {first_of_narr[k]} narasi")
        if phrase_first[k]:
            flags.append(f"pertama memakai {phrase_first[k]} frasa khas")
        if v["created"]:
            from .models import parse_time
            ct, fp = parse_time(v["created"]), parse_time(v["first_post"])
            if ct and fp and (fp - ct).days < 30:
                flags.append(f"akun baru ({(fp - ct).days} hari)")
        accounts.append({"author": k, "posts": v["posts"], "first_post": v["first_post"],
                         "platforms": sorted(v["platforms"]), "amplified_by": len(v["copied_by"]),
                         "origin_posts": v["roots"], "reach": v["reach"], "influence": round(pr.get(k, 0), 4),
                         "narratives": sorted(v["narratives"]), "stance": v["stances"].most_common(1)[0][0],
                         "community": comm_of.get(k), "first_mover_tags": v["first_mover_tags"][:8],
                         "followers": v["followers"], "flags": flags})
    accounts.sort(key=lambda a: (-a["reach"], -a["influence"], -len(a["flags"])))

    # ---------- 11. timeline & graf
    tl = defaultdict(Counter)
    for p in posts:
        tl[p.created_at.replace(minute=0, second=0, microsecond=0).isoformat()][p.platform] += 1
    nodes = [{**_brief(p, 200), "desc": desc[p.id], "root": p.id not in parent, "tags": feats[p.id]["tags"],
              "narrative": post_narr.get(p.id) or post_narr.get(root_of(p.id)), "stance": stance_of(p.text)}
             for p in posts]
    edges = [{"from": par, "to": c, "reason": reason[c], "conf": conf[c]} for c, par in parent.items()]

    return {
        "summary": {
            "posts": len(posts), "authors": len({p.author for p in posts}),
            "platforms": dict(Counter(p.platform for p in posts)),
            "first_seen": _brief(posts[0]), "last_seen": posts[-1].created_at.isoformat(),
            "first_by_platform": {pl: _brief(next(p for p in posts if p.platform == pl))
                                  for pl in dict.fromkeys(p.platform for p in posts)},
            "edges_by_reason": dict(Counter(reason.values())), "narratives": len(narratives),
            "hashtags": len(hashtags), "coordination_flags": len(coord),
            "networks": len(net["communities"]),
            "stance": dict(Counter(n["stance"] for n in nodes)),
        },
        "origin_candidates": origin[:100], "narratives": narratives[:60], "hashtags": hashtags[:200],
        "accounts": accounts[:500], "coordination": coord[:60], "account_network": net,
        "timeline": [{"hour": h, **c} for h, c in sorted(tl.items())],
        "graph": {"nodes": nodes, "edges": edges}, "params": {k: v for k, v in P.items()},
    }
