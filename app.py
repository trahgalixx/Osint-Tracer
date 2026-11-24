#!/usr/bin/env python3
"""OSINT Issue Tracer: aplikasi web.

    python app.py                 # buka http://127.0.0.1:5000
    python app.py --host 0.0.0.0 --port 8080
"""
import argparse
import csv
import io
import json
import os
import tempfile
import threading
import traceback

import networkx as nx
from flask import Flask, Response, jsonify, request, send_from_directory

from tracer import store
from tracer.collectors import import_file
from tracer.log import set_sink
from tracer.pipeline import analyze_posts, collect

# variabel lingkungan yang sudah di-set lebih diutamakan dibanding pengaturan di UI
for k in store.SECRET_KEYS:
    if os.environ.get(k):
        os.environ[f"_OSINT_ENV_{k}"] = "1"

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
store.init()
store.apply_settings()


def _run_job(cid, kind, fn):
    jid = store.new_job(cid, kind)

    def work():
        set_sink(lambda m: store.job_log(jid, m))
        try:
            fn()
            store.finish_job(jid, "done")
        except Exception as e:  # tampilkan error di log job
            store.job_log(jid, f"ERROR: {e}\n{traceback.format_exc(limit=3)}")
            store.finish_job(jid, "error")
    threading.Thread(target=work, daemon=True).start()
    return jid


# ------------------------------------------------------------------ halaman
@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/static/<path:p>")
def static_files(p):
    return send_from_directory(WEB, p)


# ------------------------------------------------------------------ kasus
@app.get("/api/cases")
def cases():
    return jsonify(store.list_cases())


@app.post("/api/cases")
def create_case():
    d = request.get_json(force=True)
    if not (d.get("name") or "").strip():
        return jsonify(error="Nama kasus wajib diisi"), 400
    cid = store.create_case(d["name"].strip(), d.get("description", ""), d.get("queries") or {})
    return jsonify(store.get_case(cid))


@app.get("/api/cases/<cid>")
def get_case(cid):
    c = store.get_case(cid)
    if not c:
        return jsonify(error="tidak ditemukan"), 404
    c["jobs"] = store.case_jobs(cid)
    return jsonify(c)


@app.patch("/api/cases/<cid>")
def patch_case(cid):
    d = request.get_json(force=True)
    store.update_case(cid, **{k: d[k] for k in ("name", "description", "queries") if k in d})
    return jsonify(store.get_case(cid))


@app.delete("/api/cases/<cid>")
def delete_case(cid):
    store.delete_case(cid)
    return jsonify(ok=True)


# ------------------------------------------------------------------ data
@app.post("/api/cases/<cid>/collect")
def start_collect(cid):
    q = request.get_json(force=True) or {}
    store.update_case(cid, queries=q)

    def fn():
        from tracer.log import log
        posts = collect(q)
        added = store.add_posts(cid, posts)
        log(f"Selesai: {len(posts)} item diambil, {added} baru disimpan")
    return jsonify(job=_run_job(cid, "collect", fn))


@app.post("/api/cases/<cid>/upload")
def upload(cid):
    f = request.files.get("file")
    if not f:
        return jsonify(error="file kosong"), 400
    platform = (request.form.get("platform") or "").strip().lower()
    mapping = {}
    for part in (request.form.get("mapping") or "").replace("\n", ",").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            mapping[k.strip()] = v.strip()
    suffix = os.path.splitext(f.filename or "")[1].lower() or ".csv"
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "upload" + suffix)
        f.save(path)
        logs = []
        set_sink(logs.append)
        try:
            posts = import_file(path, platform, mapping)
        except Exception as e:
            return jsonify(error=f"Gagal membaca file: {e}"), 400
        finally:
            set_sink(None)
    no_time = sum(1 for p in posts if p.created_at is None)
    added = store.add_posts(cid, posts)
    return jsonify(read=len(posts), added=added, no_time=no_time, log=logs)


@app.get("/api/cases/<cid>/posts")
def posts(cid):
    total, rows = store.query_posts(cid, request.args.get("q", ""), request.args.get("platform", ""),
                                    int(request.args.get("offset", 0)), min(500, int(request.args.get("limit", 100))))
    return jsonify(total=total, rows=rows)


@app.delete("/api/cases/<cid>/posts")
def delete_posts(cid):
    store.delete_posts(cid, request.args.get("platform") or None)
    return jsonify(ok=True)


# ------------------------------------------------------------------ analisis
@app.post("/api/cases/<cid>/analyze")
def start_analyze(cid):
    d = request.get_json(force=True) or {}
    params = {k: d[k] for k in ("copy_threshold", "link_threshold", "cluster_threshold", "min_narrative",
                                "coord_window_min", "coord_min_accounts", "network_window_min") if d.get(k) not in (None, "")}
    for k in list(params):
        params[k] = float(params[k]) if "threshold" in k else int(params[k])
    kw = [x.strip() for x in (d.get("keyword_filter") or "").split(",") if x.strip()]
    if kw:
        params["keyword_filter"] = kw

    def fn():
        posts = store.load_posts(cid)
        res = analyze_posts(posts, params, use_llm=bool(d.get("use_llm")))
        store.save_result(cid, res)
        s = res["summary"]
        from tracer.log import log
        log(f"Selesai: {s['posts']} post, {s['narratives']} narasi, {s['coordination_flags']} pola koordinasi")
    return jsonify(job=_run_job(cid, "analyze", fn))


@app.get("/api/cases/<cid>/result")
def result(cid):
    r = store.load_result(cid)
    return jsonify(r) if r else (jsonify(error="belum dianalisis"), 404)


@app.get("/api/jobs/<jid>")
def job(jid):
    return jsonify(store.get_job(jid) or {})


# ------------------------------------------------------------------ ekspor
def _csv(rows, cols):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return buf.getvalue()


@app.get("/api/cases/<cid>/export/<kind>")
def export(cid, kind):
    case = store.get_case(cid) or {"name": cid}
    fname = "".join(ch if ch.isalnum() else "_" for ch in case["name"])[:40] or cid
    if kind == "posts.csv":
        rows = [p.to_dict() for p in store.load_posts(cid)]
        body = _csv(rows, ["id", "platform", "kind", "created_at", "author", "text", "url", "parent_id", "source",
                           "engagement"])
        return Response(body, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={fname}_posts.csv"})
    r = store.load_result(cid)
    if not r:
        return jsonify(error="belum dianalisis"), 404
    if kind == "result.json":
        return Response(json.dumps(r, ensure_ascii=False, indent=1), mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename={fname}_hasil.json"})
    tables = {
        "sources.csv": (r["origin_candidates"], ["score", "time", "platform", "author", "text", "url", "cascade_size",
                                                 "unique_authors", "platforms", "narrative", "reasons"]),
        "narratives.csv": ([{**n, "claim": n.get("llm", {}).get("claim", ""), "first_author": n["first"]["author"],
                             "first_time": n["first"]["time"], "representative": n["representative"]["text"],
                             "top_source": n["source_attribution"][0]["author"] if n["source_attribution"] else ""}
                            for n in r["narratives"]],
                           ["id", "size", "authors", "platforms", "first_time", "first_author", "top_source", "claim",
                            "representative", "key_terms", "hashtags", "stance", "duration_hours"]),
        "accounts.csv": (r["accounts"], ["author", "posts", "first_post", "platforms", "origin_posts", "reach",
                                         "amplified_by", "influence", "narratives", "stance", "community", "flags"]),
        "hashtags.csv": (r["hashtags"], ["tag", "count", "authors", "platforms", "peak_hour", "peak_count", "narratives",
                                         "co_tags"]),
        "edges.csv": (r["graph"]["edges"], ["from", "to", "reason", "conf"]),
    }
    if kind in tables:
        rows, cols = tables[kind]
        return Response(_csv(rows, cols), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={fname}_{kind}"})
    if kind == "graph.gexf":
        G = nx.DiGraph()
        for n in r["graph"]["nodes"]:
            G.add_node(n["id"], label=n["author"], platform=n["platform"], time=n["time"] or "",
                       text=n["text"][:200], descendants=n["desc"], narrative=n["narrative"] or "", stance=n["stance"])
        for e in r["graph"]["edges"]:
            G.add_edge(e["from"], e["to"], reason=e["reason"], weight=e["conf"])
        buf = io.BytesIO()
        nx.write_gexf(G, buf)
        return Response(buf.getvalue(), mimetype="application/xml",
                        headers={"Content-Disposition": f"attachment; filename={fname}_graf.gexf"})
    return jsonify(error="jenis ekspor tidak dikenal"), 404


# ------------------------------------------------------------------ pengaturan & demo
@app.get("/api/settings")
def get_settings():
    from tracer import llm
    return jsonify(keys=store.settings_status(), llm_model=llm.MODEL)


@app.post("/api/settings")
def post_settings():
    d = request.get_json(force=True) or {}
    if d.get("CAMOUFOX_PROXY"):
        from tracer.tiktok_browser import parse_proxy
        try:
            parse_proxy(d["CAMOUFOX_PROXY"])
        except ValueError as e:
            return jsonify(error=str(e)), 400
    store.save_settings(d)
    return jsonify(keys=store.settings_status())


@app.get("/api/camoufox/status")
def camoufox_status():
    from tracer.tiktok_browser import default_profile_dir, mask_proxy
    try:
        import camoufox  # noqa: F401
        installed = True
    except ImportError:
        installed = False
    prof = default_profile_dir()
    return jsonify(installed=installed, profile=os.path.isdir(prof) and bool(os.listdir(prof)),
                   proxy=mask_proxy(os.environ.get("CAMOUFOX_PROXY")))


@app.post("/api/camoufox/test-proxy")
def camoufox_test_proxy():
    """Bandingkan IP publik tanpa dan dengan proxy (lewat layanan cek-IP publik)."""
    import requests
    from tracer.tiktok_browser import parse_proxy
    url = (request.get_json(force=True) or {}).get("proxy") or os.environ.get("CAMOUFOX_PROXY")
    if not url:
        return jsonify(error="Proxy belum diisi"), 400
    try:
        p = parse_proxy(url)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    auth = f"{requests.utils.quote(p['username'], safe='')}:{requests.utils.quote(p['password'], safe='')}@" if "username" in p else ""
    scheme, hostport = p["server"].split("://", 1)
    if scheme == "socks5":
        scheme = "socks5h"   # DNS juga lewat proxy
    full = f"{scheme}://{auth}{hostport}"
    out = {}
    try:
        out["via_proxy"] = requests.get("https://api.ipify.org?format=json", proxies={"http": full, "https": full},
                                        timeout=20).json().get("ip")
    except Exception as e:
        return jsonify(error=f"Proxy gagal dipakai: {str(e)[:200]}"), 400
    try:
        out["direct"] = requests.get("https://api.ipify.org?format=json", timeout=10).json().get("ip")
    except Exception:
        out["direct"] = None
    out["hidden"] = bool(out["direct"]) and out["direct"] != out["via_proxy"]
    return jsonify(out)


@app.post("/api/camoufox/login")
def camoufox_login():
    from tracer.tiktok_browser import open_login_browser
    return jsonify(job=_run_job("_system", "login", lambda: open_login_browser(os.environ.get("CAMOUFOX_PROXY"))))


@app.post("/api/demo")
def demo():
    from sample.make_sample import make
    cid = store.create_case("Demo: isu fiktif #AirKotaTercemar",
                            "Data rekaan untuk mencoba fitur. Kota, akun, dan media semuanya fiktif.")
    store.add_posts(cid, make())
    res = analyze_posts(store.load_posts(cid))
    store.save_result(cid, res)
    return jsonify(store.get_case(cid))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()
    print(f"OSINT Issue Tracer berjalan di http://{a.host}:{a.port}")
    app.run(host=a.host, port=a.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
