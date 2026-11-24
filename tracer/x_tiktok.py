"""Kolektor X (Twitter) dan TikTok.

X:
  - API resmi v2  : env X_BEARER_TOKEN. Endpoint /2/tweets/search/recent (7 hari terakhir) atau
                    /2/tweets/search/all (arsip penuh, butuh paket Pro/Enterprise) dengan --x-archive.
  - Apify         : env APIFY_TOKEN, actor default "apidojo/tweet-scraper".
TikTok:
  - Research API  : env TIKTOK_CLIENT_KEY + TIKTOK_CLIENT_SECRET (khusus peneliti yang disetujui TikTok).
  - Apify         : env APIFY_TOKEN, actor "clockworks/tiktok-scraper" (video) dan
                    "clockworks/tiktok-comments-scraper" (komentar).

Parser dipisah dari pemanggilan HTTP agar bisa juga dipakai untuk file JSON yang sudah diunduh.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from .models import Post, parse_time

S = requests.Session()
S.headers["User-Agent"] = "osint-issue-tracer/0.2"
VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def _log(msg):
    from .log import log
    log(f"[collect] {msg}")


def _req(method, url, **kw):
    for attempt in range(5):
        try:
            r = S.request(method, url, timeout=kw.pop("timeout", 60), **kw)
        except requests.RequestException as e:
            if attempt == 4:
                _log(f"gagal {url[:80]}: {e}")
                return None
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            reset = r.headers.get("x-rate-limit-reset")
            wait = max(5, int(reset) - int(time.time())) if reset and reset.isdigit() else 15 * (attempt + 1)
            _log(f"rate limit, tunggu {min(wait, 900)} detik")
            time.sleep(min(wait, 900))
            continue
        if not r.ok:
            _log(f"HTTP {r.status_code} {url[:80]}: {r.text[:300]}")
            return None
        return r
    return None


def _g(d, *path, default=None):
    """Ambil nilai bertingkat dengan aman: _g(d, 'author', 'userName')."""
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
    return default if d is None else d


def _int(*vals):
    return sum(int(v) for v in vals if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()))


# ======================================================================= X (Twitter)
X_FIELDS = {
    "tweet.fields": "created_at,author_id,conversation_id,referenced_tweets,public_metrics,entities,lang,in_reply_to_user_id",
    "expansions": "author_id,referenced_tweets.id,referenced_tweets.id.author_id",
    "user.fields": "username,name,created_at,public_metrics,verified",
}


def _x_tweet_to_post(t, users):
    refs = {r["type"]: r["id"] for r in t.get("referenced_tweets") or []}
    if "retweeted" in refs:
        kind, parent = "repost", refs["retweeted"]
    elif "quoted" in refs:
        kind, parent = "quote", refs["quoted"]
    elif "replied_to" in refs:
        kind, parent = "reply", refs["replied_to"]
    else:
        kind, parent = "post", ""
    u = users.get(t.get("author_id"), {})
    username = u.get("username") or t.get("author_id", "")
    m = t.get("public_metrics") or {}
    return Post(
        id=f"x:{t['id']}", platform="x", text=t.get("text", ""), created_at=parse_time(t.get("created_at")),
        author=username, url=f"https://x.com/{username}/status/{t['id']}", kind=kind,
        parent_id=f"x:{parent}" if parent else "",
        engagement=_int(m.get("like_count"), m.get("retweet_count"), m.get("reply_count"), m.get("quote_count")),
        extra={"conversation_id": t.get("conversation_id"), "lang": t.get("lang"),
               "author_created": u.get("created_at"),
               "author_followers": _g(u, "public_metrics", "followers_count")})


def parse_x_v2_page(js):
    """Parse satu halaman respons X API v2 (data + includes). Tweet yang dirujuk (yang di-RT/quote/reply)
    ikut dimasukkan karena sering kali justru itulah sumber yang lebih awal."""
    users = {u["id"]: u for u in _g(js, "includes", "users", default=[])}
    out = [_x_tweet_to_post(t, users) for t in js.get("data") or []]
    out += [_x_tweet_to_post(t, users) for t in _g(js, "includes", "tweets", default=[])]
    return out


def x_api_search(query, bearer, max_items=1000, archive=False, start=None, end=None):
    """query memakai sintaks pencarian X, mis: '(#AirKotaTercemar OR "air pdam") lang:id -is:retweet'.
    start/end: ISO 8601 (2026-11-01T00:00:00Z) atau tanggal."""
    url = "https://api.x.com/2/tweets/search/" + ("all" if archive else "recent")
    params = {"query": query, "max_results": 100, **X_FIELDS}
    if start:
        params["start_time"] = parse_time(start).strftime("%Y-%m-%dT%H:%M:%SZ")
    if end:
        params["end_time"] = parse_time(end).strftime("%Y-%m-%dT%H:%M:%SZ")
    if archive:
        params["sort_order"] = "recency"
    out, n_main = [], 0
    while n_main < max_items:
        r = _req("GET", url, params=params, headers={"Authorization": f"Bearer {bearer}"})
        if not r:
            break
        js = r.json()
        n_main += len(js.get("data") or [])
        out += parse_x_v2_page(js)
        nt = _g(js, "meta", "next_token")
        if not nt:
            break
        params["next_token"] = nt
        if archive:
            time.sleep(1.1)  # search/all: 1 request/detik
    _log(f"x api '{query}': {n_main} tweet (+{len(out) - n_main} tweet rujukan)")
    return out


def x_api_conversation(conversation_id, bearer, max_items=500, archive=False):
    """Ambil semua balasan dalam satu percakapan (thread) — berguna untuk menggali komentar post sumber."""
    return x_api_search(f"conversation_id:{conversation_id}", bearer, max_items=max_items, archive=archive)


def parse_apify_tweet(d):
    """Format output actor Apify tweet scraper (apidojo/tweet-scraper dan sejenisnya)."""
    tid = str(d.get("id") or d.get("id_str") or "")
    if not tid:
        return None
    author = _g(d, "author", "userName") or _g(d, "author", "username") or _g(d, "user", "screen_name") or d.get("username", "")
    rt = d.get("retweet") or d.get("retweetedTweet") or {}
    qt = d.get("quote") or d.get("quotedTweet") or {}
    if d.get("isRetweet") or rt:
        kind, parent = "repost", rt.get("id") if isinstance(rt, dict) else ""
    elif d.get("isQuote") or qt:
        kind, parent = "quote", (qt.get("id") if isinstance(qt, dict) else "") or d.get("quoteId", "")
    elif d.get("inReplyToId") or d.get("isReply"):
        kind, parent = "reply", d.get("inReplyToId", "")
    else:
        kind, parent = "post", ""
    p = Post(id=f"x:{tid}", platform="x", text=d.get("fullText") or d.get("text") or "",
             created_at=parse_time(d.get("createdAt") or d.get("created_at")), author=author,
             url=d.get("url") or d.get("twitterUrl") or f"https://x.com/{author}/status/{tid}", kind=kind,
             parent_id=f"x:{parent}" if parent else "",
             engagement=_int(d.get("likeCount"), d.get("retweetCount"), d.get("replyCount"), d.get("quoteCount")),
             extra={"conversation_id": d.get("conversationId"), "lang": d.get("lang"),
                    "author_created": _g(d, "author", "createdAt"),
                    "author_followers": _g(d, "author", "followers")})
    out = [p]
    for sub in (rt, qt):  # tweet yang dirujuk juga dimasukkan
        if isinstance(sub, dict) and sub.get("id"):
            q = parse_apify_tweet(sub)
            if q:
                out += q
    return out


# ======================================================================= TikTok
def parse_tiktok_video(d):
    """Format Apify (clockworks/tiktok-scraper) atau TikTok Research API (video/query)."""
    vid = str(d.get("id") or d.get("video_id") or d.get("aweme_id") or "")
    if not vid:
        return None
    a = d.get("author")
    author = (_g(d, "authorMeta", "name") or (a.get("uniqueId") if isinstance(a, dict) else a)
              or d.get("username") or "")
    text = d.get("text") or d.get("desc") or d.get("video_description") or ""
    tags = d.get("hashtag_names") or [h.get("name") for h in d.get("hashtags") or [] if isinstance(h, dict)]
    missing = [t for t in tags if t and f"#{t}".lower() not in text.lower()]
    if missing:  # pastikan hashtag ikut teranalisis walau tidak ada di caption
        text += " " + " ".join(f"#{t}" for t in missing)
    stats = d.get("stats") or {}
    return Post(
        id=f"tiktok:{vid}", platform="tiktok", text=text,
        created_at=parse_time(d.get("createTimeISO") or d.get("createTime") or d.get("create_time")),
        author=author or "", url=d.get("webVideoUrl") or f"https://www.tiktok.com/@{author}/video/{vid}",
        engagement=_int(d.get("diggCount"), d.get("shareCount"), d.get("commentCount"), d.get("like_count"),
                        d.get("share_count"), d.get("comment_count"), stats.get("diggCount"), stats.get("shareCount"),
                        stats.get("commentCount")),
        extra={"plays": d.get("playCount") or d.get("view_count") or stats.get("playCount"),
               "music": _g(d, "musicMeta", "musicName") or d.get("music_id"),
               "region": d.get("region_code"), "sound_original": _g(d, "musicMeta", "musicOriginal")})


def parse_tiktok_comment(d, video_id=""):
    cid = str(d.get("cid") or d.get("id") or "")
    if not cid:
        return None
    vid = str(video_id or d.get("video_id") or d.get("awemeId") or d.get("aweme_id") or "")
    if not vid:
        m = VIDEO_ID_RE.search(d.get("videoWebUrl") or d.get("submittedVideoUrl") or "")
        vid = m.group(1) if m else ""
    reply_to = d.get("repliesToId") or d.get("parent_comment_id") or d.get("reply_id")
    reply_to = str(reply_to) if reply_to not in (None, "", 0, "0") and str(reply_to) != vid else ""
    parent = f"tiktok:c{reply_to}" if reply_to else (f"tiktok:{vid}" if vid else "")
    return Post(
        id=f"tiktok:c{cid}", platform="tiktok", kind="comment", text=d.get("text", ""),
        created_at=parse_time(d.get("createTimeISO") or d.get("createTime") or d.get("create_time")),
        author=d.get("uniqueId") or d.get("username") or _g(d, "user", "unique_id") or "",
        url=d.get("videoWebUrl") or "", parent_id=parent,
        engagement=_int(d.get("diggCount"), d.get("like_count"), d.get("replyCommentTotal"), d.get("reply_count")))


_TT_TOKEN = {}


def _tiktok_token(key, secret):
    if _TT_TOKEN.get("exp", 0) > time.time() + 60:
        return _TT_TOKEN["tok"]
    r = _req("POST", "https://open.tiktokapis.com/v2/oauth/token/",
             data={"client_key": key, "client_secret": secret, "grant_type": "client_credentials"},
             headers={"Content-Type": "application/x-www-form-urlencoded"})
    if not r or "access_token" not in r.json():
        _log("TikTok: gagal mendapatkan token (cek TIKTOK_CLIENT_KEY/SECRET & akses Research API)")
        return None
    _TT_TOKEN.update(tok=r.json()["access_token"], exp=time.time() + r.json().get("expires_in", 7000))
    return _TT_TOKEN["tok"]


def tiktok_research_videos(keyword=None, hashtag=None, key="", secret="", start=None, end=None,
                           region=None, max_items=1000, comments_for_top=20):
    """TikTok Research API. Rentang maksimum 30 hari per query → dipecah otomatis per 30 hari."""
    tok = _tiktok_token(key, secret)
    if not tok:
        return []
    end_d = (parse_time(end) if end else datetime.now(timezone.utc)).date()
    start_d = (parse_time(start) if start else datetime.now(timezone.utc) - timedelta(days=30)).date()
    conds = []
    if keyword:
        conds.append({"operation": "IN", "field_name": "keyword", "field_values": [keyword]})
    if hashtag:
        conds.append({"operation": "IN", "field_name": "hashtag_name", "field_values": [hashtag.lstrip("#")]})
    if region:
        conds.append({"operation": "IN", "field_name": "region_code", "field_values": [region]})
    fields = "id,video_description,create_time,region_code,share_count,view_count,like_count,comment_count,music_id,hashtag_names,username"
    out = []
    win_start = start_d
    while win_start <= end_d and len(out) < max_items:
        win_end = min(win_start + timedelta(days=29), end_d)
        body = {"query": {"and": conds}, "max_count": 100, "start_date": win_start.strftime("%Y%m%d"),
                "end_date": win_end.strftime("%Y%m%d")}
        while len(out) < max_items:
            r = _req("POST", f"https://open.tiktokapis.com/v2/research/video/query/?fields={fields}", json=body,
                     headers={"Authorization": f"Bearer {tok}"})
            if not r:
                break
            data = r.json().get("data") or {}
            out += [p for p in (parse_tiktok_video(v) for v in data.get("videos") or []) if p]
            if not data.get("has_more"):
                break
            body.update(cursor=data.get("cursor"), search_id=data.get("search_id"))
        win_start = win_end + timedelta(days=1)
    n_vid = len(out)
    for v in sorted(out[:n_vid], key=lambda p: -p.engagement)[:comments_for_top]:
        vid = v.id.split(":", 1)[1]
        body, got = {"video_id": int(vid), "max_count": 100, "cursor": 0}, 0
        while got < 1000:
            r = _req("POST", "https://open.tiktokapis.com/v2/research/video/comment/list/"
                     "?fields=id,video_id,text,like_count,reply_count,parent_comment_id,create_time",
                     json=body, headers={"Authorization": f"Bearer {tok}"})
            if not r:
                break
            data = r.json().get("data") or {}
            cs = [p for p in (parse_tiktok_comment(c, vid) for c in data.get("comments") or []) if p]
            for c in cs:
                c.url = v.url
            out += cs
            got += len(cs)
            if not data.get("has_more"):
                break
            body["cursor"] = data.get("cursor")
    _log(f"tiktok research '{keyword or hashtag}': {n_vid} video, {len(out) - n_vid} komentar")
    return out


# ======================================================================= Apify
def apify_run(actor, run_input, token, timeout=600):
    url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    r = _req("POST", url, json=run_input, headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
             params={"timeout": timeout - 10, "clean": "true"})
    return r.json() if r else []


def x_apify_search(query, token, max_items=500, start=None, end=None, actor="apidojo/tweet-scraper"):
    inp = {"searchTerms": [query], "maxItems": max_items, "sort": "Latest"}
    if start:
        inp["start"] = parse_time(start).strftime("%Y-%m-%d")
    if end:
        inp["end"] = parse_time(end).strftime("%Y-%m-%d")
    out = []
    for d in apify_run(actor, inp, token):
        out += parse_apify_tweet(d) or []
    _log(f"x apify '{query}': {len(out)} tweet")
    return out


def tiktok_apify_search(query=None, hashtag=None, token="", max_items=300, comments_for_top=15,
                        actor="clockworks/tiktok-scraper", comments_actor="clockworks/tiktok-comments-scraper"):
    inp = {"resultsPerPage": max_items, "shouldDownloadVideos": False, "shouldDownloadCovers": False}
    if hashtag:
        inp["hashtags"] = [hashtag.lstrip("#")]
    if query:
        inp["searchQueries"] = [query]
    vids = [p for p in (parse_tiktok_video(d) for d in apify_run(actor, inp, token)) if p]
    out = list(vids)
    top = sorted(vids, key=lambda p: -p.engagement)[:comments_for_top]
    if top and comments_for_top:
        items = apify_run(comments_actor, {"postURLs": [v.url for v in top], "commentsPerPost": 200,
                                           "maxRepliesPerComment": 20}, token)
        out += [p for p in (parse_tiktok_comment(d) for d in items) if p]
    _log(f"tiktok apify '{query or hashtag}': {len(vids)} video, {len(out) - len(vids)} komentar")
    return out


# ======================================================================= deteksi format file
def parse_known_json(js):
    """Kenali file JSON hasil API X v2 / Apify / TikTok Research. Kembalikan None jika tidak dikenal."""
    if isinstance(js, dict) and "data" in js and isinstance(js["data"], list) and ("includes" in js or "meta" in js):
        return parse_x_v2_page(js)
    if isinstance(js, dict) and isinstance(_g(js, "data", "videos"), list):
        return [p for p in map(parse_tiktok_video, js["data"]["videos"]) if p]
    if isinstance(js, dict) and isinstance(_g(js, "data", "comments"), list):
        return [p for p in map(parse_tiktok_comment, js["data"]["comments"]) if p]
    if isinstance(js, list) and js and isinstance(js[0], dict):
        d = js[0]
        if "cid" in d or ("repliesToId" in d and "uniqueId" in d):
            return [p for p in map(parse_tiktok_comment, js) if p]
        if "authorMeta" in d or "webVideoUrl" in d:
            return [p for p in map(parse_tiktok_video, js) if p]
        if ("twitterUrl" in d or "retweetCount" in d) and isinstance(d.get("author"), dict):
            return [q for x in js for q in (parse_apify_tweet(x) or [])]
    return None
