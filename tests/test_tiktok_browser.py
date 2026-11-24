"""Uji kolektor Camoufox/TikTok terhadap situs TikTok TIRUAN lokal, memakai Chromium Playwright sebagai pengganti
Camoufox (logika halaman, gulir item terakhir, tunggu loading, tangkap JSON, komentar, balasan, dan deteksi
CAPTCHA/login/'Something went wrong' sama). Jalankan: python -m tests.test_tiktok_browser"""
import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager

from flask import Flask, redirect, request
from werkzeug.serving import make_server

from tracer import tiktok_browser as TB

app = Flask(__name__)
logging.getLogger("werkzeug").disabled = True
VISITED = []


def item(i, tag="airkotatercemar", author=None):
    return {"id": str(7300 + i), "desc": f"video {i} air pdam bau kimia #{tag}", "createTime": 1794364200 + i * 600,
            "author": {"uniqueId": author or f"akun{i}"}, "stats": {"diggCount": 100 * i, "shareCount": i,
                                                                     "commentCount": 2, "playCount": 1000 * i},
            "textExtra": [{"hashtagName": tag}], "challenges": [{"title": "LembahsariDarurat"}]}


# Daftar video "virtual": halaman berikutnya hanya dimuat saat item TERAKHIR terlihat (IntersectionObserver),
# dengan ikon loading selama memuat — meniru TikTok.
LIST_PAGE = """<!doctype html><html><body>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">%(init)s</script>
<div id="list"></div><div id="loader" data-e2e="loading" style="display:none">memuat…</div>
<script>
let cursor = 0, busy = false;
const list = document.getElementById('list'), loader = document.getElementById('loader');
async function more() {
  if (busy || cursor >= %(pages)d) return; busy = true; loader.style.display = 'block';
  const r = await fetch('%(api)s?cursor=' + cursor); const js = await r.json(); cursor++;
  await new Promise(res => setTimeout(res, 300));
  const items = js.itemList || (js.data || []).map(d => d.item);
  for (const it of items) {
    const d = document.createElement('div'); d.setAttribute('data-e2e', 'search_top-item');
    d.style.height = '420px'; d.innerHTML = '<a href="/@' + it.author.uniqueId + '/video/' + it.id + '">v</a>';
    list.appendChild(d);
  }
  loader.style.display = 'none'; busy = false; watch();
}
const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) more(); });
function watch() { io.disconnect(); const last = list.lastElementChild; if (last) io.observe(last); }
more();
</script></body></html>"""


def list_page(api, pages=3, init="{}"):
    return LIST_PAGE % {"init": init, "api": api, "pages": pages}


@app.get("/tag/<tag>")
def tag(tag):
    if tag == "rusak":
        return ('<html><body><div>Something went wrong</div>'
                '<button onclick="this.dataset.n=(+this.dataset.n||0)+1">Try again</button></body></html>')
    return list_page("/api/challenge/item_list/")


@app.get("/api/challenge/item_list/")
def challenge():
    c = int(request.args["cursor"])
    return {"itemList": [item(c * 3 + k) for k in range(3)], "hasMore": c < 2, "cursor": c + 1}


@app.get("/search")
def search():
    q = request.args.get("q", "")
    VISITED.append(request.full_path)
    if q == "perlu login":                      # TikTok mengalihkan ke beranda
        return redirect("/")
    if q == "modal":                            # jendela login + API menolak
        return """<html><body><div data-e2e="login-modal" style="width:300px;height:200px">Log in to TikTok</div>
        <script>fetch('/api/search/general/full/?cursor=0&login=1')</script></body></html>"""
    if q == "domonly":                          # hasil hanya ada di tampilan halaman
        cards = "".join(f'<div data-e2e="search_top-item"><a href="/@pembuat{i}/video/{7311234567890123456 + i}">x</a>'
                        f'<div data-e2e="search-card-video-caption">dasco cawapres #pilpres video {i}</div>'
                        f'<strong data-e2e="video-views">{i + 1},5 rb</strong></div>' for i in range(4))
        return f"<html><body>{cards}</body></html>"
    return list_page("/api/search/general/full/")


@app.get("/")
def home():
    return "<html><head><title>TikTok - Make Your Day</title></head><body>beranda</body></html>"


@app.get("/api/search/general/full/")
def search_api():
    if request.args.get("login"):
        return {"status_code": 2483, "status_msg": "Login required", "data": []}
    c = int(request.args["cursor"])
    return {"data": [{"type": 1, "item": item(50 + c * 2 + k, tag="pdamlembahsari")} for k in range(2)]}


@app.get("/@<user>")
def profile(user):
    return list_page("/api/post/item_list/", pages=2)


@app.get("/api/post/item_list/")
def user_posts():
    c = int(request.args["cursor"])
    return {"itemList": [item(80 + c * 2 + k, tag="profil", author="pemkot_ls") for k in range(2)]}


@app.get("/@<user>/video/<vid>")
def video(user, vid):
    det = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item(int(vid) - 7300, author=user)}}}}
    return f"""<!doctype html><html><body>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{json.dumps(det)}</script>
<button data-e2e="comment-icon" onclick="more()">komentar</button>
<div data-e2e="comment-list" id="cl" style="height:300px;overflow:auto"></div>
<div id="cload" data-e2e="comment-loading" style="display:none">memuat…</div>
<script>
let c = 0, busy = false; const cl = document.getElementById('cl'), ld = document.getElementById('cload');
async function more() {{
  if (busy || c >= 3) return; busy = true; ld.style.display = 'block';
  const js = await (await fetch('/api/comment/list/?aweme_id={vid}&cursor=' + c)).json(); c++;
  await new Promise(r => setTimeout(r, 250));
  for (const x of js.comments) {{
    const d = document.createElement('div'); d.className = 'DivCommentObjectWrapper'; d.style.height = '120px';
    d.innerHTML = '<span data-e2e="comment-level-1">' + x.text + '</span>' +
      (x.reply_comment_total ? '<span role="button" onclick="replies(this, \\'' + x.cid + '\\')">View ' + x.reply_comment_total + ' replies</span>' : '');
    cl.appendChild(d);
  }}
  ld.style.display = 'none'; busy = false; watch();
}}
async function replies(el, cid) {{ await fetch('/api/comment/list/reply/?comment_id=' + cid + '&item_id={vid}'); el.remove(); }}
const io = new IntersectionObserver(es => {{ if (es.some(e => e.isIntersecting)) more(); }}, {{root: cl}});
function watch() {{ io.disconnect(); const last = cl.lastElementChild; if (last) io.observe(last); }}
</script></body></html>"""


@app.get("/api/comment/list/")
def comments():
    vid, c = request.args["aweme_id"], int(request.args["cursor"])
    out = [{"cid": f"{vid}{c}{k}", "text": f"komentar {c}{k}", "create_time": 1794370000 + c * 60 + k,
            "aweme_id": vid, "user": {"unique_id": f"penonton{c}{k}"}, "digg_count": k, "reply_id": "0",
            "reply_comment_total": 2 if k == 0 else 0} for k in range(3)]
    return {"comments": out, "has_more": c < 2, "cursor": c + 1}


@app.get("/api/comment/list/reply/")
def replies():
    cid, vid = request.args["comment_id"], request.args["item_id"]
    return {"comments": [{"cid": f"{cid}r{k}", "text": f"balasan {k}: hoaks itu", "create_time": 1794370500 + k,
                          "aweme_id": vid, "user": {"unique_id": f"pembalas{k}"}, "digg_count": 1, "reply_id": cid}
                         for k in range(2)], "has_more": False}


@app.get("/tag/blocked")
def blocked():
    return '<html><body><div id="captcha-verify-container">Verifikasi</div></body></html>'


def main():
    os.environ.setdefault("OSINT_DATA_DIR", tempfile.mkdtemp())
    srv = make_server("127.0.0.1", 5099, app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:5099"
    from playwright.sync_api import sync_playwright
    seen = {}

    @contextmanager
    def launcher(headless=True, proxy=None):
        seen["proxy"] = proxy
        with sync_playwright() as pw:
            exe = "/opt/pw-browsers/chromium"
            b = pw.chromium.launch(headless=True, **({"executable_path": exe} if os.path.isfile(exe) else {}))
            ctx = b.new_context()
            yield ctx
            b.close()

    logs = []
    TB.log = logs.append
    fast = dict(launcher=launcher, base=base, delay=(0.1, 0.2))

    # 1. daftar target campuran dalam satu input
    targets = """#airkotatercemar | 9
dasco calon wakil presiden
@pemkot_ls | 4
https://www.tiktok.com/@sumber/video/7399 | 40"""
    posts = TB.collect_tiktok(targets=targets, proxy_url="socks5://u:p%40ss@10.0.0.1:1080", comments_for_top=1,
                              max_videos=6, **fast)
    by = {p.id: p for p in posts}
    vids = [p for p in posts if p.kind != "comment"]
    coms = [p for p in posts if p.kind == "comment"]
    assert seen["proxy"] == {"server": "socks5://10.0.0.1:1080", "username": "u", "password": "p@ss"}, seen
    assert any("4 target:" in l for l in logs), logs
    assert len([v for v in vids if "airkotatercemar" in v.text]) >= 9, "hashtag: item terakhir digulir → 3 halaman"
    assert VISITED[0] == "/search?q=dasco%20calon%20wakil%20presiden", VISITED
    assert sum("pdamlembahsari" in v.text for v in vids) >= 6, "pencarian: batas bawaan 6"
    assert sum(v.author == "pemkot_ls" for v in vids) >= 4, "profil akun"
    assert "tiktok:7399" in by and by["tiktok:7399"].author == "sumber", "video dari data rehidrasi"
    assert "#lembahsaridarurat" in by["tiktok:7301"].text.lower(), "hashtag challenge"
    assert sum(c.parent_id == "tiktok:7399" for c in coms) == 9, "komentar: 3 halaman lewat item terakhir di panel"
    assert by["tiktok:c739900r0"].parent_id == "tiktok:c739900", "balasan → komentar"
    assert any("membuka balasan" in l for l in logs), logs
    top = max(vids, key=lambda v: v.engagement)
    assert any(c.parent_id == top.id for c in coms), "komentar video teratas ikut diambil"

    # 2. 'Something went wrong' → klik 'Try again' sekali → dilaporkan jelas
    logs.clear()
    out = TB.collect_tiktok(targets="#rusak", comments_for_top=0, **fast)
    assert out == [] and any("Something went wrong" in l and "menolak memuat" in l for l in logs), logs
    assert any("Mencoba tombol muat ulang" in l for l in logs), logs

    # 3. CAPTCHA → berhenti dengan pesan
    logs.clear()
    out = TB.collect_tiktok(targets="#blocked", comments_for_top=0, **fast)
    assert out == [] and any("BERHENTI" in l and "verifikasi" in l for l in logs), logs

    # 4. hasil hanya di tampilan halaman → diambil dari kartu, waktu dari ID video
    logs.clear()
    out = TB.collect_tiktok(targets="domonly | 4", comments_for_top=0, **fast)
    assert len(out) == 4 and all(p.author.startswith("pembuat") for p in out), out
    assert out[0].created_at.year == 2023 and "#pilpres" in out[0].text and out[1].extra["plays"] == 2500, out[1]

    # 5. dialihkan ke beranda / jendela login → diagnosis + screenshot
    logs.clear()
    TB.collect_tiktok(targets="perlu login", comments_for_top=0, **fast)
    assert any("mengalihkan halaman" in l for l in logs), logs
    shot = [l for l in logs if "screenshot & HTML disimpan" in l]
    assert shot and os.path.isfile(shot[0].split("disimpan: ")[1].split(" / ")[0]), logs
    logs.clear()
    TB.collect_tiktok(targets="modal", comments_for_top=0, **fast)
    assert any("jendela login" in l for l in logs) and any("status_code=2483 Login required" in l for l in logs), logs

    # 6. format target & proxy
    P = TB.parse_targets("#a | 5\n@b\nhttps://www.tiktok.com/tag/c\nhttps://www.tiktok.com/search?q=d%20e\n"
                         "https://www.tiktok.com/@f\nkata kunci; #A")
    assert [(t["kind"], t["value"], t["max"]) for t in P] == [
        ("hashtag", "a", 5), ("user", "b", 100), ("hashtag", "c", 100), ("search", "d e", 100),
        ("user", "f", 100), ("search", "kata kunci", 100)], P
    assert TB.parse_proxy("1.2.3.4:8080") == {"server": "http://1.2.3.4:8080"}
    try:
        TB.parse_proxy("http://hostonly")
        raise AssertionError("harus gagal")
    except ValueError:
        pass
    assert TB.mask_proxy("http://user:rahasia@1.2.3.4:8080") == "http://1.2.3.4:8080 (dengan login)"
    srv.shutdown()
    print(f"OK  — 4 jenis target dalam satu input; {len(vids)} video, {len(coms)} komentar+balasan lewat gulir item "
          "terakhir & tunggu loading; 'Something went wrong', CAPTCHA, pengalihan, jendela login terdiagnosis")


if __name__ == "__main__":
    main()
