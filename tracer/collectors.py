"""Pengumpul data dari sumber yang bisa diakses gratis + importer file hasil scraping/ekspor.

Platform tertutup (X/Twitter, TikTok, Instagram, Facebook, YouTube) tidak di-scrape langsung di sini:
ekspor datanya (mis. dari API resmi, Apify, twscrape, Instaloader, CrowdTangle-archive, Meta Content
Library, Zeeschuimer, dsb.) lalu masukkan lewat `import_file`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

from .models import Post, parse_time
from .textutil import strip_html

UA = "Mozilla/5.0 (compatible; osint-issue-tracer/0.1; research)"
S = requests.Session()
S.headers["User-Agent"] = UA


def _log(msg):
    from .log import log
    log(f"[collect] {msg}")


def _get(url, **kw):
    for attempt in range(4):
        try:
            r = S.get(url, timeout=30, **kw)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == 3:
                _log(f"gagal {url[:90]}...: {e}")
                return None
            time.sleep(2 ** attempt)
    return None


# ---------------------------------------------------------------- Berita
def google_news(query: str, hl="id", gl="ID", max_items=100):
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    r = _get(url)
    if not r:
        return []
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        src_el = it.find("source")
        source = src_el.text if src_el is not None else ""
        link = it.findtext("link") or ""
        out.append(Post(
            id="gnews:" + hashlib.sha1(link.encode()).hexdigest()[:16],
            platform="news", kind="article", text=title + " " + strip_html(it.findtext("description") or ""),
            created_at=parse_time(it.findtext("pubDate")), author=source or "", source=source or "",
            url=link, extra={"title": title, "via": "google_news",
                             "source_url": src_el.get("url") if src_el is not None else ""}))
        if len(out) >= max_items:
            break
    _log(f"google_news '{query}': {len(out)} artikel")
    return out


def gdelt(query: str, timespan="3m", start=None, end=None, max_records=250, lang=None):
    """GDELT DOC 2.0 API (berita global, termasuk media Indonesia). timespan: 1d, 2w, 3m, ...
    start/end format YYYYMMDDHHMMSS. lang contoh: 'indonesian'."""
    q = query + (f" sourcelang:{lang}" if lang else "")
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&sort=dateasc"
           f"&maxrecords={max_records}&query={quote_plus(q)}")
    url += f"&startdatetime={start}&enddatetime={end}" if start and end else f"&timespan={timespan}"
    r = _get(url)
    if not r:
        return []
    try:
        arts = r.json().get("articles", [])
    except ValueError:
        _log(f"gdelt: respons bukan JSON: {r.text[:200]}")
        return []
    out = [Post(id="gdelt:" + hashlib.sha1(a["url"].encode()).hexdigest()[:16], platform="news",
                kind="article", text=a.get("title", ""), created_at=parse_time(a.get("seendate")),
                author=a.get("domain", ""), source=a.get("domain", ""), url=a["url"],
                extra={"title": a.get("title", ""), "lang": a.get("language"), "via": "gdelt",
                       "country": a.get("sourcecountry")}) for a in arts]
    _log(f"gdelt '{query}': {len(out)} artikel")
    return out


# ---------------------------------------------------------------- Media sosial terbuka
def mastodon_tag(tag: str, instance="mastodon.social", max_items=400):
    tag = tag.lstrip("#")
    out, max_id = [], None
    while len(out) < max_items:
        url = f"https://{instance}/api/v1/timelines/tag/{quote_plus(tag)}?limit=40"
        if max_id:
            url += f"&max_id={max_id}"
        r = _get(url)
        if not r or not r.json():
            break
        for s in r.json():
            pid = f"mastodon:{s['id']}"
            out.append(Post(
                id=pid, platform="mastodon", text=strip_html(s.get("content", "")),
                created_at=parse_time(s["created_at"]), author=s["account"]["acct"], url=s.get("url") or "",
                kind="reply" if s.get("in_reply_to_id") else "post",
                parent_id=f"mastodon:{s['in_reply_to_id']}" if s.get("in_reply_to_id") else "",
                engagement=(s.get("favourites_count") or 0) + (s.get("reblogs_count") or 0) + (s.get("replies_count") or 0)))
            max_id = s["id"]
    _log(f"mastodon #{tag}@{instance}: {len(out)} post")
    return out


def reddit_search(query: str, max_items=300, comments_for_top=10):
    out, after = [], None
    while len(out) < max_items:
        url = f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort=new&limit=100&raw_json=1"
        if after:
            url += f"&after={after}"
        r = _get(url)
        if not r:
            break
        data = r.json().get("data", {})
        for c in data.get("children", []):
            d = c["data"]
            out.append(Post(
                id=f"reddit:{d['name']}", platform="reddit", text=f"{d.get('title', '')} {d.get('selftext', '')}",
                created_at=parse_time(d.get("created_utc")), author=d.get("author", ""),
                url="https://www.reddit.com" + d.get("permalink", ""), source="r/" + d.get("subreddit", ""),
                engagement=(d.get("score") or 0) + (d.get("num_comments") or 0),
                extra={"link": d.get("url", "")}))
        after = data.get("after")
        if not after:
            break
    # komentar dari post paling ramai
    top = sorted(out, key=lambda p: -p.engagement)[:comments_for_top]
    for p in top:
        r = _get(p.url.rstrip("/") + ".json?raw_json=1&limit=200")
        if not r:
            continue
        stack = list(r.json()[1]["data"]["children"]) if isinstance(r.json(), list) else []
        while stack:
            c = stack.pop()
            if c.get("kind") != "t1":
                continue
            d = c["data"]
            out.append(Post(
                id=f"reddit:{d['name']}", platform="reddit", kind="comment", text=d.get("body", ""),
                created_at=parse_time(d.get("created_utc")), author=d.get("author", ""),
                url="https://www.reddit.com" + d.get("permalink", ""), parent_id=f"reddit:{d['parent_id']}",
                engagement=d.get("score") or 0))
            if isinstance(d.get("replies"), dict):
                stack.extend(d["replies"]["data"]["children"])
    _log(f"reddit '{query}': {len(out)} post+komentar")
    return out


def bluesky_search(query: str, handle: str, app_password: str, max_items=500):
    r = S.post("https://bsky.social/xrpc/com.atproto.server.createSession",
               json={"identifier": handle, "password": app_password}, timeout=30)
    if not r.ok:
        _log(f"bluesky login gagal: {r.status_code} {r.text[:200]}")
        return []
    tok = r.json()["accessJwt"]
    out, cursor = [], None

    def uid(uri):
        return "bluesky:" + uri if uri else ""

    while len(out) < max_items:
        url = f"https://bsky.social/xrpc/app.bsky.feed.searchPosts?q={quote_plus(query)}&limit=100&sort=latest"
        if cursor:
            url += f"&cursor={cursor}"
        r = _get(url, headers={"Authorization": f"Bearer {tok}"})
        if not r:
            break
        js = r.json()
        for p in js.get("posts", []):
            rec = p.get("record", {})
            parent = (rec.get("reply") or {}).get("parent", {}).get("uri", "")
            emb = rec.get("embed") or {}
            quoted = (emb.get("record") or {}).get("uri") or ((emb.get("record") or {}).get("record") or {}).get("uri", "")
            h = p["author"]["handle"]
            out.append(Post(
                id=uid(p["uri"]), platform="bluesky", text=rec.get("text", ""),
                created_at=parse_time(rec.get("createdAt")), author=h,
                url=f"https://bsky.app/profile/{h}/post/{p['uri'].rsplit('/', 1)[-1]}",
                kind="reply" if parent else ("quote" if quoted else "post"), parent_id=uid(parent or quoted),
                engagement=sum(p.get(k, 0) or 0 for k in ("likeCount", "repostCount", "replyCount", "quoteCount"))))
        cursor = js.get("cursor")
        if not cursor:
            break
    _log(f"bluesky '{query}': {len(out)} post")
    return out


# ---------------------------------------------------------------- Import file (X, TikTok, IG, FB, YouTube, dll)
ALIASES = {
    "id": ["id", "id_str", "tweet_id", "post_id", "comment_id", "cid", "aweme_id", "shortcode", "video_id", "status_id"],
    "text": ["text", "full_text", "rawContent", "caption", "content", "comment", "body", "message", "desc",
             "description", "title", "textOriginal", "post_text"],
    "created_at": ["created_at", "createdAt", "date", "timestamp", "time", "createTime", "create_time",
                   "taken_at", "publishedAt", "published_at", "datetime", "created_time", "createTimeISO"],
    "author": ["author", "username", "user", "screen_name", "user.username", "user.screen_name", "ownerUsername",
               "authorMeta.name", "author.uniqueId", "uniqueId", "authorDisplayName", "author_name", "from.name",
               "owner.username", "channel", "handle"],
    "url": ["url", "link", "permalink", "webVideoUrl", "postUrl", "tweet_url", "post_url"],
    "parent_id": ["parent_id", "in_reply_to_status_id", "in_reply_to_status_id_str", "inReplyToTweetId",
                  "in_reply_to", "inReplyToId", "quoted_status_id", "quotedTweet.id", "retweeted_status_id",
                  "retweetedTweet.id", "replied_to", "parentId", "reply_to", "post_id_parent", "video_id_parent"],
    "kind": ["kind", "type", "post_type"],
    "engagement": ["engagement", "likes", "like_count", "likeCount", "favorite_count", "diggCount",
                   "likesCount", "retweet_count", "shareCount", "playCount", "reactions"],
    "platform": ["platform"],
    "source": ["source", "media", "domain", "site", "outlet"],
}


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _pick(row, field, mapping):
    if field in mapping:
        return row.get(mapping[field])
    lower = {k.lower(): k for k in row}
    for a in ALIASES[field]:
        k = a if a in row else lower.get(a.lower())
        if k is not None and row.get(k) not in (None, ""):
            return row[k]
    return None


def guess_platform(row) -> str:
    keys = {k.lower() for k in row}
    url = str(row.get("url") or row.get("link") or row.get("permalink") or row.get("webVideoUrl") or "").lower()
    for dom, plat in (("tiktok.com", "tiktok"), ("instagram.com", "instagram"), ("facebook.com", "facebook"),
                      ("fb.com", "facebook"), ("youtube.com", "youtube"), ("youtu.be", "youtube"), ("x.com", "x"),
                      ("twitter.com", "x"), ("reddit.com", "reddit"), ("bsky.app", "bluesky"), ("t.me", "telegram")):
        if dom in url:
            return plat
    if keys & {"tweet_id", "retweet_count", "full_text", "in_reply_to_status_id", "quoted_status_id", "rawcontent"}:
        return "x"
    if keys & {"aweme_id", "diggcount", "authormeta.name", "webvideourl", "cid"}:
        return "tiktok"
    if keys & {"shortcode", "ownerusername", "taken_at", "likescount"}:
        return "instagram"
    if keys & {"textoriginal", "videoid", "video_id", "authordisplayname"}:
        return "youtube"
    return "unknown"


def import_file(path: str, platform: str = "", mapping: dict | None = None):
    """Baca CSV / JSON / JSONL. Kolom dikenali otomatis (lihat ALIASES) atau via mapping {field: kolom}."""
    mapping = mapping or {}
    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
        from .x_tiktok import parse_known_json
        try:
            known = parse_known_json(json.loads(raw)) if raw[:1] in "[{" else None
        except ValueError:
            known = None
        if known is None and raw[:1] == "{" and "\n" in raw:  # JSONL berisi halaman API / item Apify
            try:
                items = [json.loads(l) for l in raw.splitlines() if l.strip()]
                if all(isinstance(i, dict) and "data" in i for i in items):
                    known = [p for i in items for p in (parse_known_json(i) or [])]
                else:
                    known = parse_known_json(items)
            except ValueError:
                known = None
        if known is not None:
            _log(f"import {path}: {len(known)} item (format X/TikTok dikenali otomatis)")
            return known
        if raw.startswith("["):
            rows = json.loads(raw)
        elif raw.startswith("{") and "\n" not in raw:
            js = json.loads(raw)
            rows = next((v for v in js.values() if isinstance(v, list)), [js])
        else:
            rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
        rows = [_flatten(r) for r in rows]
    out = []
    for row in rows:
        plat = (platform or _pick(row, "platform", mapping) or guess_platform(row)).lower()
        text = str(_pick(row, "text", mapping) or "")
        author = str(_pick(row, "author", mapping) or "")
        ts = _pick(row, "created_at", mapping)
        rid = _pick(row, "id", mapping)
        if not rid:
            rid = hashlib.sha1(f"{author}|{ts}|{text}".encode()).hexdigest()[:16]
        parent = _pick(row, "parent_id", mapping)
        parent = str(parent) if parent not in (None, "", "0", "nan") else ""
        if parent and not parent.startswith(plat + ":"):
            parent = f"{plat}:{parent}"
        kind = str(_pick(row, "kind", mapping) or ("reply" if parent else ("article" if plat == "news" else "post"))).lower()
        try:
            eng = int(float(_pick(row, "engagement", mapping) or 0))
        except ValueError:
            eng = 0
        out.append(Post(id=f"{plat}:{rid}", platform=plat, text=text, created_at=parse_time(ts), author=author,
                        url=str(_pick(row, "url", mapping) or ""), kind=kind, parent_id=parent,
                        source=str(_pick(row, "source", mapping) or ""), engagement=eng))
    _log(f"import {path}: {len(out)} baris ({platform or 'platform dari kolom'})")
    return out
