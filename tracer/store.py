"""Penyimpanan lokal: kasus, post, job, hasil analisis, dan pengaturan (SQLite + file JSON)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

from .models import Post

DATA_DIR = os.environ.get("OSINT_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB = os.path.join(DATA_DIR, "osint.db")
SETTINGS = os.path.join(DATA_DIR, "settings.json")
SECRET_KEYS = ["ANTHROPIC_API_KEY", "X_BEARER_TOKEN", "APIFY_TOKEN", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
               "BSKY_HANDLE", "BSKY_APP_PASSWORD", "CAMOUFOX_PROXY"]
_lock = threading.Lock()


def _conn():
    os.makedirs(os.path.join(DATA_DIR, "results"), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, name TEXT, description TEXT, created REAL,
                                          queries TEXT DEFAULT '{}', updated REAL);
        CREATE TABLE IF NOT EXISTS posts (case_id TEXT, id TEXT, platform TEXT, created_at TEXT, data TEXT,
                                          PRIMARY KEY (case_id, id));
        CREATE INDEX IF NOT EXISTS posts_case ON posts(case_id, created_at);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, case_id TEXT, kind TEXT, status TEXT, log TEXT,
                                         created REAL, finished REAL);
        """)


# ------------------------------------------------------------------ kasus
def list_cases():
    with _conn() as c:
        rows = c.execute("""SELECT cs.*, (SELECT COUNT(*) FROM posts p WHERE p.case_id = cs.id) AS n_posts
                            FROM cases cs ORDER BY COALESCE(updated, created) DESC""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["queries"] = json.loads(d["queries"] or "{}")
        d["has_result"] = os.path.exists(result_path(d["id"]))
        out.append(d)
    return out


def get_case(cid):
    with _conn() as c:
        r = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
        n = c.execute("SELECT COUNT(*) FROM posts WHERE case_id=?", (cid,)).fetchone()[0]
        plats = dict(c.execute("SELECT platform, COUNT(*) FROM posts WHERE case_id=? GROUP BY platform", (cid,)).fetchall())
    if not r:
        return None
    d = dict(r)
    d["queries"] = json.loads(d["queries"] or "{}")
    d["n_posts"], d["platforms"] = n, plats
    d["has_result"] = os.path.exists(result_path(cid))
    return d


def create_case(name, description="", queries=None, cid=None):
    cid = cid or uuid.uuid4().hex[:10]
    with _conn() as c:
        c.execute("INSERT INTO cases (id, name, description, created, queries, updated) VALUES (?,?,?,?,?,?)",
                  (cid, name, description, time.time(), json.dumps(queries or {}), time.time()))
    return cid


def update_case(cid, **fields):
    if "queries" in fields:
        fields["queries"] = json.dumps(fields["queries"])
    fields["updated"] = time.time()
    with _conn() as c:
        c.execute(f"UPDATE cases SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), cid))


def delete_case(cid):
    with _conn() as c:
        c.execute("DELETE FROM posts WHERE case_id=?", (cid,))
        c.execute("DELETE FROM jobs WHERE case_id=?", (cid,))
        c.execute("DELETE FROM cases WHERE id=?", (cid,))
    if os.path.exists(result_path(cid)):
        os.remove(result_path(cid))


# ------------------------------------------------------------------ post
def add_posts(cid, posts):
    rows = [(cid, p.id, p.platform, p.created_at.isoformat() if p.created_at else None,
             json.dumps(p.to_dict(), ensure_ascii=False)) for p in posts]
    with _lock, _conn() as c:
        before = c.execute("SELECT COUNT(*) FROM posts WHERE case_id=?", (cid,)).fetchone()[0]
        c.executemany("INSERT OR REPLACE INTO posts (case_id, id, platform, created_at, data) VALUES (?,?,?,?,?)", rows)
        after = c.execute("SELECT COUNT(*) FROM posts WHERE case_id=?", (cid,)).fetchone()[0]
        c.execute("UPDATE cases SET updated=? WHERE id=?", (time.time(), cid))
    return after - before


def load_posts(cid):
    with _conn() as c:
        rows = c.execute("SELECT data FROM posts WHERE case_id=? ORDER BY created_at", (cid,)).fetchall()
    return [Post.from_dict(json.loads(r[0])) for r in rows]


def query_posts(cid, q="", platform="", offset=0, limit=100):
    sql, args = "SELECT data FROM posts WHERE case_id=?", [cid]
    if platform:
        sql += " AND platform=?"
        args.append(platform)
    if q:
        sql += " AND data LIKE ?"
        args.append(f"%{q}%")
    with _conn() as c:
        total = c.execute(sql.replace("SELECT data", "SELECT COUNT(*)"), args).fetchone()[0]
        rows = c.execute(sql + " ORDER BY created_at LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
    return total, [json.loads(r[0]) for r in rows]


def delete_posts(cid, platform=None):
    with _conn() as c:
        if platform:
            c.execute("DELETE FROM posts WHERE case_id=? AND platform=?", (cid, platform))
        else:
            c.execute("DELETE FROM posts WHERE case_id=?", (cid,))


# ------------------------------------------------------------------ hasil
def result_path(cid):
    return os.path.join(DATA_DIR, "results", f"{cid}.json")


def save_result(cid, res):
    with open(result_path(cid), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, default=str)


def load_result(cid):
    p = result_path(cid)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ job
def new_job(cid, kind):
    jid = uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute("INSERT INTO jobs (id, case_id, kind, status, log, created) VALUES (?,?,?,?,?,?)",
                  (jid, cid, kind, "running", "", time.time()))
    return jid


def job_log(jid, line):
    with _lock, _conn() as c:
        c.execute("UPDATE jobs SET log = log || ? WHERE id=?", (time.strftime("%H:%M:%S ") + line + "\n", jid))


def finish_job(jid, status):
    with _conn() as c:
        c.execute("UPDATE jobs SET status=?, finished=? WHERE id=?", (status, time.time(), jid))


def get_job(jid):
    with _conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return dict(r) if r else None


def case_jobs(cid, limit=10):
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs WHERE case_id=? ORDER BY created DESC LIMIT ?",
                                           (cid, limit)).fetchall()]


# ------------------------------------------------------------------ pengaturan (token disimpan lokal)
def load_settings():
    if os.path.exists(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_settings(new):
    cur = load_settings()
    for k, v in new.items():
        if k in SECRET_KEYS and v is not None:
            if v == "":
                cur.pop(k, None)
            elif not v.startswith("••"):
                cur[k] = v.strip()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(cur, f)
    try:
        os.chmod(SETTINGS, 0o600)
    except OSError:
        pass
    apply_settings()


def apply_settings():
    """Token dari file pengaturan dipakai jika variabel lingkungan belum di-set."""
    for k, v in load_settings().items():
        if k in SECRET_KEYS and v and not os.environ.get(f"_OSINT_ENV_{k}"):
            os.environ[k] = v


def settings_status():
    s = load_settings()
    out = {}
    for k in SECRET_KEYS:
        v = os.environ.get(k) or s.get(k)
        out[k] = {"set": bool(v), "masked": ("••••" + v[-4:]) if v and len(v) > 8 else ("••••" if v else ""),
                  "from_env": bool(os.environ.get(f"_OSINT_ENV_{k}"))}
    return out
