"""Pipeline pengumpulan & analisis yang dipakai bersama oleh aplikasi web dan CLI."""
from __future__ import annotations

import os

from . import collectors as C
from . import x_tiktok as XT
from .log import log


def _lst(v):
    if not v:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.replace("\n", ";").split(";") if x.strip()]
    return [x for x in v if x]


def collect(q: dict):
    """q: {gnews, gdelt, gdelt_lang, timespan, mastodon, mastodon_instance, reddit, bluesky, x, x_archive, x_apify,
    x_thread, tiktok, tiktok_tag, tiktok_region, tiktok_apify, start_date, end_date, max_items, comments_for_top}"""
    E = os.environ
    posts = []
    start, end = q.get("start_date") or None, q.get("end_date") or None
    max_items = int(q.get("max_items") or 500)
    top_c = int(q.get("comments_for_top") or 15)

    for s in _lst(q.get("gnews")):
        posts += C.google_news(s)
    for s in _lst(q.get("gdelt")):
        g_start = g_end = None
        if start and end:
            g_start, g_end = start.replace("-", "") + "000000", end.replace("-", "") + "235959"
        posts += C.gdelt(s, timespan=q.get("timespan") or "3m", start=g_start, end=g_end,
                         lang=q.get("gdelt_lang") or None)
    for s in _lst(q.get("mastodon")):
        posts += C.mastodon_tag(s, instance=q.get("mastodon_instance") or "mastodon.social")
    for s in _lst(q.get("reddit")):
        posts += C.reddit_search(s)
    for s in _lst(q.get("bluesky")):
        if E.get("BSKY_HANDLE") and E.get("BSKY_APP_PASSWORD"):
            posts += C.bluesky_search(s, E["BSKY_HANDLE"], E["BSKY_APP_PASSWORD"])
        else:
            log("[collect] Bluesky dilewati: isi BSKY_HANDLE & BSKY_APP_PASSWORD di Pengaturan")

    for s in _lst(q.get("x")):
        if E.get("X_BEARER_TOKEN") and not q.get("x_apify"):
            posts += XT.x_api_search(s, E["X_BEARER_TOKEN"], max_items=max_items, archive=bool(q.get("x_archive")),
                                     start=start, end=end)
        elif E.get("APIFY_TOKEN"):
            posts += XT.x_apify_search(s, E["APIFY_TOKEN"], max_items=max_items, start=start, end=end)
        else:
            log("[collect] X dilewati: isi X_BEARER_TOKEN atau APIFY_TOKEN di Pengaturan")
    for cid in _lst(q.get("x_thread")):
        if E.get("X_BEARER_TOKEN"):
            posts += XT.x_api_conversation(cid, E["X_BEARER_TOKEN"], archive=bool(q.get("x_archive")))
        else:
            log("[collect] thread X butuh X_BEARER_TOKEN")

    jobs = [("keyword", s) for s in _lst(q.get("tiktok"))] + [("hashtag", s) for s in _lst(q.get("tiktok_tag"))]
    for typ, val in jobs:
        if E.get("TIKTOK_CLIENT_KEY") and not q.get("tiktok_apify"):
            posts += XT.tiktok_research_videos(**{typ: val}, key=E["TIKTOK_CLIENT_KEY"],
                                               secret=E.get("TIKTOK_CLIENT_SECRET", ""), start=start, end=end,
                                               region=q.get("tiktok_region") or None, max_items=max_items,
                                               comments_for_top=top_c)
        elif E.get("APIFY_TOKEN"):
            posts += XT.tiktok_apify_search(query=val if typ == "keyword" else None,
                                            hashtag=val if typ == "hashtag" else None, token=E["APIFY_TOKEN"],
                                            max_items=max_items, comments_for_top=top_c)
        else:
            log("[collect] TikTok dilewati: isi TIKTOK_CLIENT_KEY/SECRET atau APIFY_TOKEN di Pengaturan")
    # ---- TikTok lewat browser Camoufox (daftar target satu kolom; kolom lama tetap diterima)
    tb_text = q.get("tt_b_targets") or ""
    tb_tags, tb_kw, tb_urls = _lst(q.get("tt_b_tags")), _lst(q.get("tt_b_keywords")), _lst(q.get("tt_b_urls"))
    if tb_text.strip() or tb_tags or tb_kw or tb_urls:
        from .tiktok_browser import collect_tiktok
        try:
            posts += collect_tiktok(targets=tb_text, hashtags=tb_tags, keywords=tb_kw, video_urls=tb_urls,
                                    proxy_url=E.get("CAMOUFOX_PROXY") or None,
                                    headless=not q.get("tt_b_show_browser"),
                                    max_videos=int(q.get("tt_b_max_videos") or 100),
                                    comments_for_top=int(q.get("tt_b_comments_top") or 0),
                                    max_comments=int(q.get("tt_b_max_comments") or 300),
                                    include_replies=q.get("tt_b_replies", True) is not False)
        except Exception as e:  # sumber lain tetap disimpan
            log(f"[camoufox] {e}")
    return posts


def analyze_posts(posts, params=None, use_llm=False):
    from .analyze import analyze
    from . import llm
    res = analyze(posts, **(params or {}))
    res["llm_used"] = False
    if use_llm:
        if llm.available():
            log("[claude] meringkas narasi…")
            llm.enrich(res, {p.id: p for p in posts})
            res["llm_used"] = any("llm" in n for n in res["narratives"])
        else:
            log("[claude] dilewati: ANTHROPIC_API_KEY belum diisi")
    return res
