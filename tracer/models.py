from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from dateutil import parser as dtparser

# Zona waktu default untuk timestamp tanpa zona (WIB / UTC+7)
DEFAULT_TZ = timezone(timedelta(hours=7))


def parse_time(value, default_tz=DEFAULT_TZ) -> Optional[datetime]:
    """Ubah berbagai format waktu (ISO, RFC822, epoch, GDELT 20260101T101500Z) ke datetime UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit() and len(value.strip()) >= 9):
        v = float(value)
        if v > 1e12:  # milidetik
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    else:
        try:
            dt = dtparser.parse(str(value))
        except (ValueError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc)


@dataclass
class Post:
    id: str                       # unik, format "<platform>:<id asli>"
    platform: str                 # x, tiktok, instagram, facebook, mastodon, bluesky, reddit, news, ...
    text: str
    created_at: Optional[datetime]
    author: str = ""
    url: str = ""
    kind: str = "post"            # post | reply | comment | repost | quote | article
    parent_id: str = ""           # id (format sama) dari post yang dibalas/di-repost/di-quote
    source: str = ""              # nama media / domain untuk berita
    engagement: int = 0           # like+share+comment bila tersedia
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat() if self.created_at else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Post":
        d = dict(d)
        d["created_at"] = parse_time(d.get("created_at"))
        known = {f for f in cls.__dataclass_fields__}
        extra = d.pop("extra", {}) or {}
        for k in list(d):
            if k not in known:
                extra[k] = d.pop(k)
        return cls(**d, extra=extra)


def save_jsonl(posts, path):
    with open(path, "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(Post.from_dict(json.loads(line)))
    return out
