"""Kolektor TikTok lewat browser Camoufox.

Membuka halaman TikTok seperti pengguna biasa (hashtag, pencarian, profil akun, halaman video), menangkap data
JSON yang dimuat halaman itu sendiri (dengan cadangan dari tampilan halaman), lalu mengubahnya ke format Post.
Pola pemuatan: item terakhir digulir ke tengah layar (scrollIntoView), lalu menunggu ikon loading hilang.

Prinsip:
- Hanya membaca halaman publik yang bisa Anda lihat sendiri, dengan sesi login Anda sendiri (profil tersimpan).
- Kecepatan dibatasi: jeda acak antar langkah dan batas jumlah video/komentar.
- Satu proxy opsional yang Anda atur sendiri (untuk menyembunyikan IP Anda), tanpa rotasi otomatis.
- Bila TikTok meminta verifikasi (CAPTCHA) atau login, proses berhenti dan meminta Anda menyelesaikannya
  manual lewat "Buka browser untuk login". Tool ini tidak mencoba membobol verifikasi.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from contextlib import contextmanager
from urllib.parse import quote, unquote, urlsplit

from .log import log
from .proxy_bridge import make_bridge, needs_bridge
from .x_tiktok import parse_tiktok_comment, parse_tiktok_video

API_PATTERNS = ("/api/challenge/item_list", "/api/search/", "/api/post/item_list", "/api/recommend/item_list",
                "/api/comment/list", "/api/item/detail", "/api/related/item_list", "/api/user/detail")
CAPTCHA_SELECTORS = ("#captcha-verify-container", ".captcha_verify_container", "#captcha_container",
                     "div[class*='captcha']", "iframe[src*='captcha']")
LOGIN_SELECTORS = ("[data-e2e='login-modal']", "#login-modal", "div[class*='LoginModal']",
                   "div[class*='DivLoginContainer']", "[data-e2e='login-title']")
DOM_CARDS_JS = """() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/video/"]')) {
    const m = a.href.match(/@([^/?#]+)\\/video\\/(\\d+)/);
    if (!m || seen.has(m[2])) continue;
    seen.add(m[2]);
    const card = a.closest('[data-e2e^="search"], [class*="DivItemContainer"], [class*="ItemContainer"]')
                 || a.parentElement?.parentElement || a;
    const cap = card.querySelector('[data-e2e="search-card-video-caption"], [data-e2e="search-card-desc"], [data-e2e="video-desc"], [data-e2e="challenge-item-desc"]');
    const views = card.querySelector('[data-e2e="video-views"], strong[data-e2e*="views"], [class*="PlayCount"]');
    out.push({author: decodeURIComponent(m[1]), id: m[2], href: a.href.split('?')[0],
              desc: ((cap || {}).innerText || a.getAttribute('title') || a.innerText || '').trim().slice(0, 2000),
              views: ((views || {}).innerText || '').trim()});
  }
  return out;
}"""
REHYDRATION_IDS = ("__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE", "__NEXT_DATA__")
VIDEO_URL_RE = re.compile(r"tiktok\.com/@([^/?#]+)/video/(\d+)")


class VerificationRequired(Exception):
    pass


# --------------------------------------------------------------------------- proxy
def parse_proxy(url: str | None):
    """'http://user:pass@host:port' atau 'socks5://host:port' → dict Playwright/Camoufox."""
    if not url:
        return None
    url = url.strip()
    if "://" not in url:
        url = "http://" + url
    u = urlsplit(url)
    if not u.hostname or not u.port:
        raise ValueError("Format proxy: skema://[user:pass@]host:port, mis. http://user:pass@1.2.3.4:8080")
    out = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        out["username"] = unquote(u.username)
        out["password"] = unquote(u.password or "")
    return out


def mask_proxy(url: str | None) -> str:
    if not url:
        return ""
    try:
        p = parse_proxy(url)
    except ValueError:
        return "(format tidak valid)"
    return p["server"] + (" (dengan login)" if "username" in p else "")


# --------------------------------------------------------------------------- peluncur browser
def default_profile_dir():
    from .store import DATA_DIR
    return os.path.join(DATA_DIR, "camoufox_profile")


import threading
_BROWSER_LOCK = threading.Lock()   # satu profil = satu browser Camoufox pada satu waktu


@contextmanager
def launch(headless=True, proxy=None, profile_dir=None):
    """Context manager → BrowserContext Camoufox dengan profil tersimpan.
    Proxy SOCKS dengan username/password otomatis dilewatkan jembatan lokal (Firefox tidak mendukungnya langsung)."""
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as e:
        raise RuntimeError("Camoufox belum terpasang. Jalankan: pip install camoufox && python -m camoufox fetch") from e
    profile_dir = profile_dir or default_profile_dir()
    os.makedirs(profile_dir, exist_ok=True)
    if not _BROWSER_LOCK.acquire(blocking=False):
        raise RuntimeError("Browser Camoufox lain masih berjalan (mis. jendela login masih terbuka). "
                           "Tutup jendela itu dulu atau tunggu job sebelumnya selesai, lalu ulangi.")
    bridge = None
    if needs_bridge(proxy):
        bridge = make_bridge(proxy).start()
        log(f"[camoufox] proxy SOCKS dengan login dilewatkan jembatan lokal {bridge.url}")
        proxy = {"server": bridge.url}
    opts = {"headless": headless, "persistent_context": True, "user_data_dir": profile_dir}
    if proxy:
        opts["proxy"] = proxy
    try:
        with Camoufox(**opts) as ctx:
            yield ctx
    finally:
        if bridge:
            bridge.stop()
        _BROWSER_LOCK.release()


# --------------------------------------------------------------------------- parsing respons TikTok web
def items_from_json(js):
    """Ambil (video, komentar) dari berbagai bentuk JSON TikTok web."""
    videos, comments = [], []
    if not isinstance(js, dict):
        return videos, comments
    for it in js.get("itemList") or js.get("item_list") or []:
        videos.append(it)
    for d in js.get("data") or []:                      # /api/search/general/full
        if isinstance(d, dict) and isinstance(d.get("item"), dict):
            videos.append(d["item"])
    if isinstance(js.get("itemInfo"), dict) and js["itemInfo"].get("itemStruct"):
        videos.append(js["itemInfo"]["itemStruct"])
    for c in js.get("comments") or []:
        comments.append(c)
    # data rehidrasi di HTML (halaman video / hashtag)
    scope = js.get("__DEFAULT_SCOPE__") or {}
    det = scope.get("webapp.video-detail") or {}
    if _get(det, "itemInfo", "itemStruct"):
        videos.append(det["itemInfo"]["itemStruct"])
    im = js.get("ItemModule")                              # format lama SIGI_STATE
    if isinstance(im, dict):
        videos.extend(v for v in im.values() if isinstance(v, dict))
    return videos, comments


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def count_from_text(t: str) -> int:
    """'1.2M', '3,4 rb', '12 jt', '987' → angka."""
    t = (t or "").strip().lower().replace(" ", "")
    m = re.match(r"([\d.,]+)([kmb]|rb|jt|m)?", t)
    if not m:
        return 0
    num, unit = m.group(1), m.group(2) or ""
    if unit:
        num = num.replace(",", ".")
    else:
        num = num.replace(",", "").replace(".", "")
    try:
        v = float(num)
    except ValueError:
        return 0
    return int(v * {"k": 1e3, "rb": 1e3, "m": 1e6, "jt": 1e6, "b": 1e9}.get(unit, 1))


def time_from_id(vid) -> int | None:
    """ID video TikTok menyimpan waktu unggah (detik Unix) di 32 bit teratas."""
    try:
        ts = int(vid) >> 32
    except (TypeError, ValueError):
        return None
    return ts if 1_400_000_000 < ts < 4_000_000_000 else None


def video_from_dom_card(c):
    return parse_tiktok_video(normalize_web_video({
        "id": c["id"], "desc": c.get("desc", ""), "author": {"uniqueId": c["author"]},
        "webVideoUrl": c.get("href") or "", "playCount": count_from_text(c.get("views", "")),
        "source_dom": True}))


def normalize_web_video(it):
    """Lengkapi field video TikTok web agar parser bersama mengenalinya."""
    it = dict(it)
    if not (it.get("createTime") or it.get("createTimeISO") or it.get("create_time")):
        it["createTime"] = time_from_id(it.get("id"))
    tags = [t.get("hashtagName") for t in it.get("textExtra") or [] if isinstance(t, dict) and t.get("hashtagName")]
    tags += [c.get("title") for c in it.get("challenges") or [] if isinstance(c, dict) and c.get("title")]
    if tags and not it.get("hashtags"):
        it["hashtags"] = [{"name": t} for t in dict.fromkeys(tags)]
    a = it.get("author")
    if isinstance(a, dict) and a.get("uniqueId") and not it.get("webVideoUrl"):
        it["webVideoUrl"] = f"https://www.tiktok.com/@{a['uniqueId']}/video/{it.get('id')}"
    return it


def normalize_web_comment(c):
    c = dict(c)
    c.setdefault("diggCount", c.get("digg_count"))
    c.setdefault("replyCommentTotal", c.get("reply_comment_total"))
    if not c.get("uniqueId"):
        c["uniqueId"] = _get(c, "user", "unique_id") or _get(c, "user", "uniqueId") or ""
    if not c.get("createTime") and c.get("create_time"):
        c["createTime"] = c["create_time"]
    return c


def parse_rehydration(html: str):
    out = []
    for sid in REHYDRATION_IDS:
        m = re.search(rf'<script[^>]+id="{sid}"[^>]*>(.*?)</script>', html, re.S)
        if m:
            try:
                out.append(json.loads(m.group(1)))
            except ValueError:
                pass
    return out


# --------------------------------------------------------------------------- daftar target (input teks)
def parse_targets(text, default_videos=100, default_comments=300):
    """Satu target per baris (atau dipisah ';'):
        #hashtag | 200          → video dari halaman hashtag (maks 200)
        @akun                   → video dari profil akun
        https://www.tiktok.com/@akun/video/123 | 500  → komentar video itu (maks 500)
        https://www.tiktok.com/tag/x, /search?q=..., /@akun  → dikenali dari URL
        kata kunci bebas        → pencarian TikTok
    Angka setelah '|' = batas per target (video untuk hashtag/akun/pencarian, komentar untuk URL video)."""
    if isinstance(text, (list, tuple)):
        text = "\n".join(text)
    out, seen = [], set()
    for raw in re.split(r"[\n;]", text or ""):
        line = raw.strip()
        if not line:
            continue
        limit = None
        m = re.match(r"^(.*?)\s*\|\s*(\d+)\s*$", line)
        if m:
            line, limit = m.group(1).strip(), int(m.group(2))
        t = None
        vm = VIDEO_URL_RE.search(line)
        if vm:
            t = {"kind": "video", "value": f"https://www.tiktok.com/@{vm.group(1)}/video/{vm.group(2)}"}
        elif "tiktok.com" in line:
            u = urlsplit(line if "://" in line else "https://" + line)
            path = u.path.rstrip("/")
            if path.startswith("/tag/"):
                t = {"kind": "hashtag", "value": unquote(path[5:])}
            elif path.startswith("/search"):
                q = dict(x.split("=", 1) for x in u.query.split("&") if "=" in x).get("q", "")
                t = {"kind": "search", "value": unquote(q.replace("+", " "))}
            elif path.startswith("/@"):
                t = {"kind": "user", "value": unquote(path[2:].split("/")[0])}
        elif line.startswith("#"):
            t = {"kind": "hashtag", "value": line.lstrip("#").strip()}
        elif line.startswith("@") and " " not in line:
            t = {"kind": "user", "value": line.lstrip("@")}
        else:
            t = {"kind": "search", "value": line}
        if not t or not t["value"]:
            continue
        key = (t["kind"], t["value"].lower())
        if key in seen:
            continue
        seen.add(key)
        t["max"] = limit or (default_comments if t["kind"] == "video" else default_videos)
        out.append(t)
    return out


# --------------------------------------------------------------------------- skrip halaman
VIDEO_ITEM_SEL = ('[data-e2e="search_top-item"], [data-e2e="search_video-item"], [data-e2e="search-card-item"], '
                  '[data-e2e="challenge-item"], [data-e2e="user-post-item"], div[class*="DivItemContainer"]')
COMMENT_ITEM_SEL = ('[data-e2e="comment-level-1"], [data-e2e="comment-level-2"], div[class*="CommentItemContainer"], '
                    'div[class*="DivCommentObjectWrapper"]')
COMMENT_LIST_SEL = "[data-e2e='comment-list'], [class*='CommentListContainer'], [class*='DivCommentListContainer']"
LOADER_SEL = ('[data-e2e="loading"], [data-e2e="comment-loading"], [class*="DivLoadingContainer"], '
              '[class*="LoadingContainer"], svg[class*="Loading"], [class*="TuxLoading"]')
ERROR_TEXTS = ("Something went wrong", "Terjadi kesalahan", "Ada yang salah", "Couldn't load", "Tidak dapat memuat")
RETRY_TEXTS = ("Try again", "Coba lagi", "Refresh", "Muat ulang")
REPLY_BTN_RE = r"(view|lihat)\s+\d*\s*(more\s+)?(repl|balas)"

SCROLL_LAST_JS = """([itemSel, listSel]) => {
  // gulir item terakhir ke tengah layar → memicu halaman berikutnya (pola yang sama dengan pengguna menggulir)
  const items = document.querySelectorAll(itemSel);
  if (items.length) { items[items.length - 1].scrollIntoView({block: 'center'}); return items.length; }
  const links = document.querySelectorAll('a[href*="/video/"]');
  if (links.length && !listSel) { links[links.length - 1].scrollIntoView({block: 'center'}); return links.length; }
  const box = listSel && document.querySelector(listSel);
  (box || document.scrollingElement).scrollBy(0, 1500);
  return 0;
}"""
LOADER_VISIBLE_JS = """(sel) => [...document.querySelectorAll(sel)].some(e => e.offsetParent !== null && e.getClientRects().length)"""
ERROR_PAGE_JS = """(texts) => { const t = (document.body && document.body.innerText) || '';
  return texts.find(x => t.includes(x)) || ''; }"""
CLICK_TEXT_JS = """([texts, max]) => {
  let n = 0;
  for (const b of document.querySelectorAll('button, [role="button"], p, span, div')) {
    if (n >= max) break;
    const t = (b.innerText || '').trim();
    if (!t || t.length > 40 || b.children.length > 2 || b.dataset.osintClicked) continue;
    if (texts.some(x => t.toLowerCase() === x.toLowerCase())) { b.dataset.osintClicked = '1'; b.click(); n++; }
  }
  return n;
}"""
CLICK_REPLIES_JS = """([re, max]) => {
  const rx = new RegExp(re, 'i'); let n = 0;
  for (const b of document.querySelectorAll('[data-e2e="view-more-replies"], [class*="ReplyActionContainer"] span, p, span, div[role="button"]')) {
    if (n >= max) break;
    const t = (b.innerText || '').trim();
    if (!t || t.length > 40 || b.dataset.osintClicked || !rx.test(t)) continue;
    b.dataset.osintClicked = '1'; b.scrollIntoView({block: 'center'}); b.click(); n++;
  }
  return n;
}"""


# --------------------------------------------------------------------------- kolektor
class TikTokBrowserCollector:
    def __init__(self, ctx, max_videos=100, comments_for_top=10, max_comments=300, delay=(2.0, 5.0),
                 base="https://www.tiktok.com", sleep=time.sleep, include_replies=True, max_reply_clicks=20):
        self.ctx, self.base = ctx, base.rstrip("/")
        self.max_videos, self.comments_for_top, self.max_comments = max_videos, comments_for_top, max_comments
        self.include_replies, self.max_reply_clicks = include_replies, max_reply_clicks
        self.delay, self.sleep = delay, sleep
        self.videos, self.comments = {}, {}
        self.api_log = []          # (path, status, jumlah video, jumlah komentar, status_code, pesan)
        self.debug_dir = None
        self.page = ctx.pages[0] if getattr(ctx, "pages", None) else ctx.new_page()
        self.page.on("response", self._on_response)

    # -- penangkapan respons
    def _on_response(self, resp):
        url = resp.url
        if "/api/" not in url or not any(p in url for p in API_PATTERNS):
            return
        path = urlsplit(url).path
        try:
            js = resp.json()
        except Exception as e:
            self.api_log.append((path, resp.status, 0, 0, None, f"bukan JSON ({type(e).__name__})"))
            return
        nv, nc = self._ingest(js)
        code = js.get("status_code", js.get("statusCode")) if isinstance(js, dict) else None
        msg = (js.get("status_msg") or js.get("statusMsg") or "") if isinstance(js, dict) else ""
        if isinstance(js, dict) and (js.get("verify_event") or js.get("verifyConfig") or js.get("need_verify")):
            msg = (msg + " [butuh verifikasi]").strip()
        self.api_log.append((path, resp.status, nv, nc, code, msg))

    def _ingest(self, js):
        nv = nc = 0
        vids, coms = items_from_json(js)
        for v in vids:
            p = parse_tiktok_video(normalize_web_video(v))
            if p and p.id not in self.videos:
                self.videos[p.id] = p
                nv += 1
            elif p and self.videos[p.id].extra.get("source_dom"):
                self.videos[p.id] = p          # data API lebih lengkap daripada kartu DOM
        for c in coms:
            p = parse_tiktok_comment(normalize_web_comment(c))
            if p and p.id not in self.comments:
                self.comments[p.id] = p
                nc += 1
        return nv, nc

    def _ingest_dom(self):
        try:
            cards = self.page.evaluate(DOM_CARDS_JS)
        except Exception:
            return 0
        n = 0
        for c in cards:
            p = video_from_dom_card(c)
            if p and p.id not in self.videos:
                p.extra["source_dom"] = True
                self.videos[p.id] = p
                n += 1
        return n

    # -- keadaan halaman
    def _login_wall(self):
        for sel in LOGIN_SELECTORS:
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return True
            except Exception:
                pass
        return False

    def _wait_loader_gone(self, timeout=15.0):
        """Tunggu ikon loading hilang (lebih andal daripada jeda tetap)."""
        end = time.time() + timeout
        self.page.wait_for_timeout(300)
        while time.time() < end:
            try:
                if not self.page.evaluate(LOADER_VISIBLE_JS, LOADER_SEL):
                    return True
            except Exception:
                return True
            self.page.wait_for_timeout(400)
        return False

    def _error_page(self):
        """Deteksi halaman 'Something went wrong'. Klik 'Coba lagi' sekali; bila masih, laporkan."""
        try:
            hit = self.page.evaluate(ERROR_PAGE_JS, list(ERROR_TEXTS))
        except Exception:
            return ""
        if not hit:
            return ""
        log(f"[camoufox]   TikTok menampilkan \"{hit}\". Mencoba tombol muat ulang sekali…")
        try:
            if self.page.evaluate(CLICK_TEXT_JS, [list(RETRY_TEXTS), 1]):
                self._pause()
                self._wait_loader_gone()
                hit = self.page.evaluate(ERROR_PAGE_JS, list(ERROR_TEXTS))
        except Exception:
            pass
        return hit

    def _wait_results(self, store, timeout=15.0):
        """Tunggu sampai data pertama tertangkap (API atau kartu di halaman)."""
        start, before = time.time(), len(store)
        while time.time() - start < timeout:
            if len(store) > before:
                return True
            self.page.wait_for_timeout(500)
            if store is self.videos and self._ingest_dom():
                return True
        return False

    def _diagnose(self, label, expect_path, error_text=""):
        """Dipanggil bila hasil 0: catat alasan yang paling mungkin & simpan screenshot/HTML."""
        url = self.page.url
        try:
            title = self.page.title()
        except Exception:
            title = ""
        log(f"[camoufox] {label}: 0 hasil. Halaman akhir: {url} (judul: {title[:80]!r})")
        if error_text:
            log(f"[camoufox]   → TikTok menolak memuat hasil (\"{error_text}\"). Ini biasanya berarti TikTok "
                "menandai sesi/IP ini sebagai otomatis. Coba: login ulang lewat Pengaturan, jalankan dengan jendela "
                "browser terlihat, kurangi jumlah target, atau cek apakah proxy pemicunya (coba sekali tanpa proxy). "
                "Bila tetap, gunakan jalur resmi (TikTok Research API) atau Apify.")
        if expect_path and urlsplit(url).path.rstrip("/") != expect_path.rstrip("/"):
            log("[camoufox]   → TikTok mengalihkan halaman. Biasanya karena belum login: klik "
                "\"Buka browser untuk login / verifikasi\" di Pengaturan, login, tutup jendelanya, lalu ulangi.")
        if self._login_wall():
            log("[camoufox]   → TikTok menampilkan jendela login. Login dulu lewat tombol di Pengaturan.")
        recent = self.api_log[-6:]
        if not recent:
            log("[camoufox]   → tidak ada respons API TikTok yang tertangkap (halaman mungkin belum termuat / "
                "dialihkan / format TikTok berubah).")
        for path, st, nv, nc, code, msg in recent:
            log(f"[camoufox]   API {path} HTTP {st}: {nv} video, {nc} komentar"
                + (f", status_code={code}" if code not in (None, 0) else "") + (f" {msg}" if msg else ""))
        try:
            from .store import DATA_DIR
            d = self.debug_dir or os.path.join(DATA_DIR, "debug")
            os.makedirs(d, exist_ok=True)
            stem = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + "_" + re.sub(r"\W+", "_", label)[:40])
            self.page.screenshot(path=stem + ".png", full_page=False)
            with open(stem + ".html", "w", encoding="utf-8") as f:
                f.write(self.page.content())
            log(f"[camoufox]   screenshot & HTML disimpan: {stem}.png / .html")
        except Exception as e:
            log(f"[camoufox]   gagal menyimpan screenshot: {e}")

    def _pause(self, factor=1.0):
        self.sleep(random.uniform(*self.delay) * factor)

    def _check_blocked(self):
        for sel in CAPTCHA_SELECTORS:
            try:
                if self.page.query_selector(sel):
                    raise VerificationRequired(
                        "TikTok meminta verifikasi (CAPTCHA). Buka \"Buka browser untuk login\" di Pengaturan, "
                        "selesaikan verifikasinya secara manual, lalu jalankan lagi.")
            except VerificationRequired:
                raise
            except Exception:
                pass

    def _goto(self, url):
        log(f"[camoufox] membuka {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._pause()
        self._check_blocked()
        self._wait_loader_gone()
        try:
            for js in parse_rehydration(self.page.content()):
                self._ingest(js)
        except Exception:
            pass

    def _scroll_until(self, store, target, item_sel, list_sel=None, max_idle=4, max_steps=80):
        """Gulir item terakhir ke tengah layar, tunggu loading hilang, ulangi sampai target / tidak ada data baru."""
        idle, last = 0, len(store)
        for _ in range(max_steps):
            if len(store) >= target:
                break
            try:
                self.page.evaluate(SCROLL_LAST_JS, [item_sel, list_sel])
            except Exception:
                self.page.mouse.wheel(0, random.randint(1400, 2600))
            self._wait_loader_gone()
            self._pause(0.6)
            self._check_blocked()
            if store is self.videos:
                self._ingest_dom()
            if len(store) == last:
                idle += 1
                if idle >= max_idle:
                    break
            else:
                idle, last = 0, len(store)

    # -- sumber video (hashtag / pencarian / akun)
    def _collect_page(self, url, label, expect_path, limit):
        before = len(self.videos)
        self._goto(url)
        err = self._error_page()
        if not err:
            self._wait_results(self.videos)
            self._scroll_until(self.videos, before + limit, VIDEO_ITEM_SEL)
        got = len(self.videos) - before
        dom = sum(1 for v in list(self.videos.values())[before:] if v.extra.get("source_dom"))
        log(f"[camoufox] {label}: {got} video" + (f" ({dom} dari tampilan halaman)" if dom else ""))
        if not got:
            self._diagnose(label, expect_path, err or self._error_page())

    def hashtag(self, tag, limit=None):
        t = quote(tag.lstrip("#"))
        self._collect_page(f"{self.base}/tag/{t}", f"#{tag}", f"/tag/{t}", limit or self.max_videos)

    def search(self, keyword, limit=None):
        self._collect_page(f"{self.base}/search?q={quote(keyword)}", f"cari '{keyword}'", "/search",
                           limit or self.max_videos)

    def user(self, name, limit=None):
        n = quote(name.lstrip("@"))
        self._collect_page(f"{self.base}/@{n}", f"@{name}", f"/@{n}", limit or self.max_videos)

    # -- komentar video
    def video_comments(self, url, limit=None):
        m = VIDEO_URL_RE.search(url)
        vid = m.group(2) if m else ""
        if m and not url.startswith(self.base):      # target ditulis sebagai URL tiktok.com
            url = f"{self.base}/@{m.group(1)}/video/{vid}"
        before = len(self.comments)
        self._goto(url)
        err = self._error_page()
        if err:
            self._diagnose(f"komentar {vid}", None, err)
            return
        for sel in ("[data-e2e='comment-icon']", "button[aria-label*='omment']", "[data-e2e='browse-comment']"):
            try:
                el = self.page.query_selector(sel)
                if el:
                    el.click()
                    self._wait_loader_gone()
                    break
            except Exception:
                pass
        target = before + (limit or self.max_comments)
        self._scroll_until(self.comments, target, COMMENT_ITEM_SEL, COMMENT_LIST_SEL, max_steps=60)
        if self.include_replies and len(self.comments) < target:
            clicks = 0
            while clicks < self.max_reply_clicks and len(self.comments) < target:
                n = self.page.evaluate(CLICK_REPLIES_JS, [REPLY_BTN_RE, 3])
                if not n:
                    break
                clicks += n
                self._wait_loader_gone()
                self._pause(0.5)
                self._check_blocked()
            if clicks:
                log(f"[camoufox]   membuka balasan: {clicks} kali")
        got = len(self.comments) - before
        for c in self.comments.values():   # komentar tanpa video_id → hubungkan ke video ini
            if vid and not c.parent_id:
                c.parent_id = f"tiktok:{vid}"
            if not c.url:
                c.url = url
        log(f"[camoufox] komentar {vid or url[-30:]}: {got}")

    def run(self, targets):
        video_targets = []
        for t in targets:
            k, v, lim = t["kind"], t["value"], t.get("max")
            try:
                if k == "hashtag":
                    self.hashtag(v, lim)
                elif k == "search":
                    self.search(v, lim)
                elif k == "user":
                    self.user(v, lim)
                elif k == "video":
                    video_targets.append((v, lim))
            except VerificationRequired:
                raise
            except Exception as e:
                log(f"[camoufox] lewati {k} '{v}': {str(e)[:160]}")
        urls = [u for u, _ in video_targets]
        if self.comments_for_top:
            top = sorted(self.videos.values(),
                         key=lambda p: (-p.engagement, -(p.extra.get("plays") or 0)))[:self.comments_for_top]
            video_targets += [(v.url, None) for v in top if v.url not in urls]
        for u, lim in video_targets:
            try:
                self.video_comments(u, lim)
            except VerificationRequired:
                raise
            except Exception as e:
                log(f"[camoufox] lewati {u}: {str(e)[:160]}")
        return list(self.videos.values()) + list(self.comments.values())


def collect_tiktok(targets="", hashtags=(), keywords=(), video_urls=(), proxy_url=None, headless=True,
                   max_videos=100, comments_for_top=10, max_comments=300, include_replies=True,
                   delay=(2.0, 5.0), launcher=None, base="https://www.tiktok.com"):
    """Pintu masuk utama. `targets` = teks daftar target (lihat parse_targets). Parameter hashtags/keywords/
    video_urls tetap diterima agar kasus lama tetap jalan. launcher bisa diganti (untuk pengujian)."""
    lines = [targets] if isinstance(targets, str) else list(targets)
    lines += [f"#{h.lstrip('#')}" for h in hashtags] + list(keywords) + list(video_urls)
    tlist = parse_targets("\n".join(x for x in lines if x), max_videos, max_comments)
    if not tlist:
        log("[camoufox] tidak ada target")
        return []
    log(f"[camoufox] {len(tlist)} target: " + ", ".join(f"{t['kind']}:{t['value'][:40]}(≤{t['max']})" for t in tlist))
    proxy = parse_proxy(proxy_url) if proxy_url else None
    if proxy:
        log(f"[camoufox] memakai proxy {mask_proxy(proxy_url)}")
    else:
        log("[camoufox] tanpa proxy: TikTok akan melihat IP Anda sendiri")
    cm = (launcher or launch)(headless=headless, proxy=proxy)
    try:
        ctx = cm.__enter__()
    except Exception as e:
        msg = str(e)
        hint = ("File browser Camoufox belum terunduh. Jalankan sekali: python -m camoufox fetch"
                if "github" in msg.lower() or "fetch" in msg.lower() or "not installed" in msg.lower()
                else "Periksa proxy dan instalasi Camoufox (pip install camoufox && python -m camoufox fetch)")
        raise RuntimeError(f"Gagal menjalankan Camoufox: {msg[:200]}. {hint}") from None
    try:
        col = TikTokBrowserCollector(ctx, max_videos=max_videos, comments_for_top=comments_for_top,
                                     max_comments=max_comments, delay=delay, base=base,
                                     include_replies=include_replies)
        try:
            posts = col.run(tlist)
        except VerificationRequired as e:
            log(f"[camoufox] BERHENTI: {e}")
            posts = list(col.videos.values()) + list(col.comments.values())
        except Exception as e:  # simpan apa pun yang sudah tertangkap
            log(f"[camoufox] berhenti karena error: {str(e)[:200]}")
            posts = list(col.videos.values()) + list(col.comments.values())
    finally:
        cm.__exit__(None, None, None)
    log(f"[camoufox] total: {sum(1 for p in posts if p.kind != 'comment')} video, "
        f"{sum(1 for p in posts if p.kind == 'comment')} komentar")
    return posts


def open_login_browser(proxy_url=None, url="https://www.tiktok.com/login", timeout_min=15):
    """Buka Camoufox terlihat dengan profil tersimpan agar Anda bisa login / menyelesaikan verifikasi manual.
    Hanya berguna bila aplikasi dijalankan di komputer Anda sendiri (bukan server tanpa layar)."""
    proxy = parse_proxy(proxy_url) if proxy_url else None
    with launch(headless=False, proxy=proxy) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url)
        log("[camoufox] browser terbuka. Login / selesaikan verifikasi, lalu tutup jendela browser.")
        end = time.time() + timeout_min * 60
        while time.time() < end:
            try:
                if not ctx.pages:
                    break
                ctx.pages[0].wait_for_timeout(1000)
            except Exception:
                break
    log("[camoufox] sesi login disimpan di profil")
