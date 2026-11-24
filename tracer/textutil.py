from __future__ import annotations

import html
import re
import unicodedata
import zlib
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

HASHTAG_RE = re.compile(r"(?<![\w&/])#(\w{2,100})", re.UNICODE)
MENTION_RE = re.compile(r"(?<![\w/])@([A-Za-z0-9_.]{2,30})")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "igshid", "igsh", "si", "ref", "ref_src", "ref_url", "feature",
    "s", "t", "share", "mibextid", "_rdc", "_rdr", "page",
}

# stopword ringkas Indonesia + Inggris (untuk normalisasi teks)
STOPWORDS = set("""
yang dan di ke dari ini itu untuk dengan pada adalah juga ada tidak akan sudah atau karena dalam
oleh sebagai bisa saja kita kami mereka dia ia aku saya kamu anda nya lah kah pun para jadi agar
the a an of to in on and or is are was were be been for with at by from as it this that rt via
""".split())


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>", " ", s or "", flags=re.I)
    return html.unescape(TAG_RE.sub("", s)).strip()


def norm_url(u: str) -> str:
    """Normalisasi URL agar link yang sama (beda tracking param / m. / www.) dianggap sama."""
    try:
        u = u.strip().rstrip(".,;:!?")
        parts = urlsplit(u)
        host = parts.netloc.lower()
        for pre in ("www.", "m.", "mobile.", "amp."):
            if host.startswith(pre):
                host = host[len(pre):]
        q = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_PARAMS]
        path = re.sub(r"/amp/?$", "", parts.path).rstrip("/")
        return urlunsplit(("https", host, path, urlencode(q), ""))
    except ValueError:
        return u


def extract_hashtags(text: str):
    return sorted({h.lower() for h in HASHTAG_RE.findall(text or "")})


def extract_mentions(text: str):
    return sorted({m.lower().rstrip(".") for m in MENTION_RE.findall(text or "")})


def extract_urls(text: str):
    return sorted({norm_url(u) for u in URL_RE.findall(text or "")})


def tokens(text: str):
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = URL_RE.sub(" ", t)
    t = MENTION_RE.sub(" ", t)
    t = t.replace("#", " ")
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"(\w)\1{2,}", r"\1\1", t)  # "bangeeettt" -> "bangeett"
    return [w for w in t.split() if w not in STOPWORDS and not w.isdigit()]


def shingles(toks, k=3):
    if not toks:
        return set()
    if len(toks) < k:
        return {" ".join(toks)}
    return {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MinHashLSH:
    """MinHash + LSH sederhana untuk mencari pasangan teks mirip tanpa O(n^2)."""
    PRIME = (1 << 61) - 1

    def __init__(self, num_perm=64, bands=16):
        assert num_perm % bands == 0
        self.num_perm, self.bands, self.rows = num_perm, bands, num_perm // bands
        # koefisien deterministik
        self.coef = [((i * 2654435761 + 97) % self.PRIME or 1, (i * 40503 + 11) % self.PRIME) for i in range(num_perm)]
        self.buckets = defaultdict(list)

    def signature(self, sh: set):
        base = [zlib.crc32(s.encode("utf-8")) for s in sh]
        return [min(((a * x + b) % self.PRIME) for x in base) for a, b in self.coef]

    def add(self, key, sh: set):
        if not sh:
            return
        sig = self.signature(sh)
        for band in range(self.bands):
            chunk = tuple(sig[band * self.rows:(band + 1) * self.rows])
            self.buckets[(band, chunk)].append(key)

    def candidate_pairs(self):
        pairs = set()
        for keys in self.buckets.values():
            if len(keys) < 2 or len(keys) > 2000:
                continue
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    a, b = keys[i], keys[j]
                    pairs.add((a, b) if a < b else (b, a))
        return pairs
