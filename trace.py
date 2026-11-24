#!/usr/bin/env python3
"""OSINT Issue Tracer — CLI.

  CLI ini untuk otomasi/terjadwal. Untuk pemakaian sehari-hari jalankan aplikasi web: python app.py

  python trace.py collect  --gnews "kata kunci" --gdelt "kata kunci" --mastodon tagnya \
                           --reddit "kata kunci" --import data_x.csv:x -o data/raw.jsonl
  python trace.py analyze  -i data/raw.jsonl -o out/
  python trace.py demo     # contoh dengan data fiktif
"""
import argparse
import csv
import json
import os
import sys

import networkx as nx

from tracer import collectors as C
from tracer import x_tiktok as XT
from tracer.models import load_jsonl, save_jsonl
from tracer.pipeline import analyze_posts


def cmd_collect(a):
    posts = []
    for q in a.gnews or []:
        posts += C.google_news(q, hl=a.hl, gl=a.gl)
    for q in a.gdelt or []:
        posts += C.gdelt(q, timespan=a.timespan, start=a.start, end=a.end, lang=a.gdelt_lang)
    for t in a.mastodon or []:
        posts += C.mastodon_tag(t, instance=a.mastodon_instance)
    for q in a.reddit or []:
        posts += C.reddit_search(q)
    for q in a.bluesky or []:
        h, pw = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
        if not (h and pw):
            print("Set BSKY_HANDLE dan BSKY_APP_PASSWORD untuk Bluesky", file=sys.stderr)
            continue
        posts += C.bluesky_search(q, h, pw)
    # ---- X
    for q in a.x or []:
        if os.environ.get("X_BEARER_TOKEN") and not a.x_apify:
            posts += XT.x_api_search(q, os.environ["X_BEARER_TOKEN"], max_items=a.max_items,
                                     archive=a.x_archive, start=a.start_date, end=a.end_date)
        elif os.environ.get("APIFY_TOKEN"):
            posts += XT.x_apify_search(q, os.environ["APIFY_TOKEN"], max_items=a.max_items,
                                       start=a.start_date, end=a.end_date)
        else:
            print("X: set X_BEARER_TOKEN (API resmi) atau APIFY_TOKEN", file=sys.stderr)
    for cid in a.x_thread or []:
        if os.environ.get("X_BEARER_TOKEN"):
            posts += XT.x_api_conversation(cid, os.environ["X_BEARER_TOKEN"], archive=a.x_archive)
        else:
            print("--x-thread butuh X_BEARER_TOKEN", file=sys.stderr)
    # ---- TikTok
    tt_jobs = [("q", q) for q in a.tiktok or []] + [("tag", t) for t in a.tiktok_tag or []]
    for typ, val in tt_jobs:
        kw = {"keyword": val} if typ == "q" else {"hashtag": val}
        if os.environ.get("TIKTOK_CLIENT_KEY") and not a.tiktok_apify:
            posts += XT.tiktok_research_videos(**kw, key=os.environ["TIKTOK_CLIENT_KEY"],
                                               secret=os.environ.get("TIKTOK_CLIENT_SECRET", ""),
                                               start=a.start_date, end=a.end_date, region=a.tiktok_region,
                                               max_items=a.max_items, comments_for_top=a.comments_for_top)
        elif os.environ.get("APIFY_TOKEN"):
            posts += XT.tiktok_apify_search(query=kw.get("keyword"), hashtag=kw.get("hashtag"),
                                            token=os.environ["APIFY_TOKEN"], max_items=a.max_items,
                                            comments_for_top=a.comments_for_top)
        else:
            print("TikTok: set TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET (Research API) atau APIFY_TOKEN", file=sys.stderr)
    for spec in a.imports or []:
        path, _, plat = spec.partition(":") if not os.path.exists(spec) else (spec, "", "")
        mapping = dict(m.split("=", 1) for m in (a.map or []))
        posts += C.import_file(path, plat, mapping)
    if a.append and os.path.exists(a.output):
        old = load_jsonl(a.output)
        ids = {p.id for p in posts}
        posts = [p for p in old if p.id not in ids] + posts
    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    save_jsonl(posts, a.output)
    print(f"Tersimpan {len(posts)} item → {a.output}")


def export_gexf(res, path):
    G = nx.DiGraph()
    for n in res["graph"]["nodes"]:
        G.add_node(n["id"], label=n["author"], platform=n["platform"], time=n["time"] or "",
                   text=n["text"][:200], descendants=n["desc"], root=n["root"])
    for e in res["graph"]["edges"]:
        G.add_edge(e["from"], e["to"], reason=e["reason"], weight=e["conf"])
    nx.write_gexf(G, path)


def write_csv(rows, path, cols):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in r.items()})


def cmd_analyze(a):
    posts = []
    for path in a.input:
        posts += load_jsonl(path) if path.endswith(".jsonl") else C.import_file(path)
    res = analyze_posts(posts, {"copy_threshold": a.threshold, "link_threshold": a.link_threshold,
                                "cluster_threshold": a.cluster_threshold, "coord_window_min": a.window,
                                "coord_min_accounts": a.min_accounts, "keyword_filter": a.filter}, use_llm=a.llm)
    os.makedirs(a.output, exist_ok=True)
    with open(os.path.join(a.output, "result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    write_csv(res["origin_candidates"], os.path.join(a.output, "origin_candidates.csv"),
              ["score", "time", "platform", "author", "text", "url", "cascade_size", "unique_authors", "platforms",
               "narrative", "reasons"])
    write_csv([{**n, "claim": n.get("llm", {}).get("claim", ""), "representative": n["representative"]["text"],
                "top_source": (n["source_attribution"] or [{}])[0].get("author", "")} for n in res["narratives"]],
              os.path.join(a.output, "narratives.csv"),
              ["id", "size", "authors", "platforms", "top_source", "claim", "representative", "key_terms", "stance"])
    write_csv(res["hashtags"], os.path.join(a.output, "hashtags.csv"),
              ["tag", "count", "authors", "platforms", "peak_hour", "peak_count", "co_tags", "first"])
    write_csv(res["accounts"], os.path.join(a.output, "accounts.csv"),
              ["author", "posts", "first_post", "platforms", "origin_posts", "reach", "amplified_by", "influence",
               "narratives", "flags"])
    write_csv(res["graph"]["edges"], os.path.join(a.output, "edges.csv"), ["from", "to", "reason", "conf"])
    export_gexf(res, os.path.join(a.output, "graph.gexf"))
    s = res["summary"]
    print(f"\n{s['posts']} post, {s['authors']} akun, {s['narratives']} narasi, platform {s['platforms']}")
    print("\nTop 5 kandidat sumber:")
    for o in res["origin_candidates"][:5]:
        print(f"  {o['score']:>7}  {o['time'][:16]}  [{o['platform']}] {o['author']}  cascade={o['cascade_size']}"
              f"  → {o['text'][:70]!r}")
    print("\nNarasi:")
    for n in res["narratives"][:5]:
        src = n["source_attribution"][0]["author"] if n["source_attribution"] else "-"
        print(f"  {n['id']}: {n['size']} post, sumber terkuat {src} → {n['representative']['text'][:70]!r}")
    print(f"\nOutput di {a.output}/ (result.json, *.csv, graph.gexf). Untuk tampilan interaktif: python app.py")


def cmd_demo(a):
    from sample.make_sample import make
    path = "sample/sample_posts.jsonl"
    save_jsonl(make(), path)
    cmd_analyze(argparse.Namespace(input=[path], output="out_demo", threshold=0.5, link_threshold=0.25,
                                   cluster_threshold=0.25, window=10, min_accounts=4, filter=None, llm=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="kumpulkan data")
    c.add_argument("--gnews", action="append", help="query Google News RSS")
    c.add_argument("--hl", default="id"), c.add_argument("--gl", default="ID")
    c.add_argument("--gdelt", action="append", help="query GDELT (berita global)")
    c.add_argument("--gdelt-lang", default=None, help="mis. indonesian")
    c.add_argument("--timespan", default="3m"), c.add_argument("--start"), c.add_argument("--end")
    c.add_argument("--mastodon", action="append", help="hashtag Mastodon (tanpa #)")
    c.add_argument("--mastodon-instance", default="mastodon.social")
    c.add_argument("--reddit", action="append", help="query Reddit")
    c.add_argument("--bluesky", action="append", help="query Bluesky (butuh BSKY_HANDLE/BSKY_APP_PASSWORD)")
    c.add_argument("--x", action="append", help='query X, mis. "#AirKotaTercemar OR \\"air pdam\\" lang:id"')
    c.add_argument("--x-thread", action="append", help="conversation_id X untuk ambil semua balasannya")
    c.add_argument("--x-archive", action="store_true", help="pakai /search/all (arsip penuh, paket Pro)")
    c.add_argument("--x-apify", action="store_true", help="paksa pakai Apify walau ada X_BEARER_TOKEN")
    c.add_argument("--tiktok", action="append", help="kata kunci TikTok")
    c.add_argument("--tiktok-tag", action="append", help="hashtag TikTok (tanpa #)")
    c.add_argument("--tiktok-region", default=None, help="kode negara Research API, mis. ID")
    c.add_argument("--tiktok-apify", action="store_true", help="paksa pakai Apify walau ada kredensial Research API")
    c.add_argument("--start-date", help="awal rentang X/TikTok, mis. 2026-11-01")
    c.add_argument("--end-date", help="akhir rentang X/TikTok")
    c.add_argument("--max-items", type=int, default=500, help="batas item per query X/TikTok")
    c.add_argument("--comments-for-top", type=int, default=15, help="ambil komentar untuk N video TikTok teratas")
    c.add_argument("--import", dest="imports", action="append", help="file.csv[:platform] / file.json[:platform]")
    c.add_argument("--map", action="append", help="pemetaan kolom, mis. text=isi_komentar")
    c.add_argument("-o", "--output", default="data/raw.jsonl")
    c.add_argument("--append", action="store_true", help="gabung dengan file output yang sudah ada")
    c.set_defaults(fn=cmd_collect)

    z = sub.add_parser("analyze", help="analisis & buat laporan")
    z.add_argument("-i", "--input", action="append", required=True, help=".jsonl hasil collect atau .csv/.json")
    z.add_argument("-o", "--output", default="out")
    z.add_argument("--threshold", type=float, default=0.5, help="ambang kemiripan teks (Jaccard 0-1)")
    z.add_argument("--link-threshold", type=float, default=0.25, help="ambang kemiripan makna untuk tautan")
    z.add_argument("--cluster-threshold", type=float, default=0.25, help="ambang kemiripan makna untuk narasi")
    z.add_argument("--llm", action="store_true", help="ringkas narasi dengan Claude (butuh ANTHROPIC_API_KEY)")
    z.add_argument("--window", type=int, default=10, help="jendela menit untuk deteksi koordinasi")
    z.add_argument("--min-accounts", type=int, default=4)
    z.add_argument("--filter", action="append", help="hanya post yang mengandung kata ini (boleh berulang)")
    z.set_defaults(fn=cmd_analyze)

    d = sub.add_parser("demo", help="jalankan dengan data fiktif")
    d.set_defaults(fn=cmd_demo)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
