/* OSINT Issue Tracer: frontend (vanilla JS) */
const S = { cases: [], caseId: null, case: null, result: null, tab: "ringkasan", narr: null, jobs: {} };
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = t => t ? new Date(t).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" }) : "–";
const fmtShort = t => t ? new Date(t).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const num = n => (n ?? 0).toLocaleString("id-ID");
const PLAT_ORDER = ["x", "facebook", "instagram", "tiktok", "news", "reddit", "mastodon", "bluesky", "youtube"];
const PLAT_LABEL = { x: "X", facebook: "Facebook", instagram: "Instagram", tiktok: "TikTok", news: "Berita", reddit: "Reddit", mastodon: "Mastodon", bluesky: "Bluesky", youtube: "YouTube" };
const REASON = { reply: "balasan", comment: "komentar", repost: "repost", quote: "quote", "copy-text": "salin teks", "shared-url": "link sama", "similar-narrative": "narasi mirip", "shared-hashtag": "hashtag sama" };
const STANCES = ["menyebarkan", "mempertanyakan", "membantah", "netral"];
const platColor = p => { const i = PLAT_ORDER.indexOf(p); return css("--c" + ((i < 0 ? p.length : i) % 8)); };
const stColor = s => css("--s-" + s) || css("--s-netral");
const pill = p => `<span class="pill" style="background:${platColor(p)}">${esc(PLAT_LABEL[p] || p)}</span>`;
const stPill = s => `<span class="pill" style="background:${stColor(s)}">${esc(s)}</span>`;
const link = (u, t) => u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a>` : esc(t);
const _lst = v => Array.isArray(v) ? v.filter(Boolean) : String(v || "").split(/[;\n]/).map(x => x.trim()).filter(Boolean);
const plist = o => Object.entries(o || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${pill(k)} <span class="small mut">${v}</span>`).join(" ");

async function api(path, opt = {}) {
  const r = await fetch(path, { headers: opt.body && !(opt.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opt });
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || r.statusText);
  return data;
}
function toast(msg) { const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 3500); }
function go(h) { location.hash = h; $("#side").classList.remove("open"); }

/* ---------------------------------------------------------------- tema */
function toggleTheme() {
  const cur = document.documentElement.dataset.theme;
  const next = cur === "dark" ? "light" : cur === "light" ? "" : (matchMedia("(prefers-color-scheme: dark)").matches ? "light" : "dark");
  if (next) document.documentElement.dataset.theme = next; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("theme", next); } catch (e) {}
  render();
}
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}

/* ---------------------------------------------------------------- sidebar */
async function loadCases() {
  S.cases = await api("/api/cases");
  $("#caseList").innerHTML = S.cases.length ? S.cases.map(c => `
    <div class="case-item ${c.id === S.caseId ? "active" : ""}" onclick="go('#/case/${c.id}')">
      <span>${esc(c.name)}</span><small>${num(c.n_posts)} post${c.has_result ? " · dianalisis" : ""}</small>
    </div>`).join("") : `<div class="mut small" style="padding:0 6px">Belum ada kasus.</div>`;
}

/* ---------------------------------------------------------------- router */
window.addEventListener("hashchange", route);
async function route() {
  const h = location.hash.slice(2).split("/");
  if (h[0] === "case" && h[1]) {
    if (S.caseId !== h[1]) { S.caseId = h[1]; S.result = null; S.narr = null; await loadCase(); }
    S.tab = h[2] || (S.result ? "ringkasan" : "data");
  } else { S.caseId = null; S.case = null; S.result = null; }
  await loadCases();
  render();
}
async function loadCase() {
  try { S.case = await api(`/api/cases/${S.caseId}`); } catch (e) { S.case = null; toast("Kasus tidak ditemukan"); return; }
  try { S.result = await api(`/api/cases/${S.caseId}/result`); } catch (e) { S.result = null; }
}
const menuBtn = `<button class="btn sm menu-btn" onclick="$('#side').classList.toggle('open')">☰</button>`;

function render() {
  const m = $("#main");
  if (!S.caseId) return viewHome(m);
  if (!S.case) { m.innerHTML = `${menuBtn}<div class="empty">Kasus tidak ditemukan.</div>`; return; }
  const c = S.case, r = S.result;
  const tabs = [["data", "Data"], ["ringkasan", "Ringkasan"], ["narasi", "Narasi"], ["penyebaran", "Graf penyebaran"], ["jaringan", "Jaringan & koordinasi"], ["hashtag", "Hashtag"], ["akun", "Akun"]];
  m.innerHTML = `
    <div class="row spread">
      <div class="row">${menuBtn}<div><h1>${esc(c.name)}</h1>
        <div class="mut small">${num(c.n_posts)} post · ${plist(c.platforms)}${(() => { const j = r && S.case.jobs?.find(j => j.kind === "analyze" && j.status === "done"); return j ? ` · dianalisis ${fmt(j.finished * 1000)}` : r ? " · dianalisis" : ""; })()}</div></div></div>
      <div class="row">
        <button class="btn primary" onclick="openAnalyze()" ${c.n_posts ? "" : "disabled"}>${r ? "Analisis ulang" : "Analisis"}</button>
        <select class="btn" style="width:auto" onchange="if(this.value){location.href='/api/cases/${c.id}/export/'+this.value;this.value=''}" ${c.n_posts ? "" : "disabled"}>
          <option value="">Ekspor…</option><option value="posts.csv">Semua post (CSV)</option>
          ${r ? `<option value="sources.csv">Kandidat sumber (CSV)</option><option value="narratives.csv">Narasi (CSV)</option>
          <option value="accounts.csv">Akun (CSV)</option><option value="hashtags.csv">Hashtag (CSV)</option><option value="edges.csv">Tautan penyebaran (CSV)</option>
          <option value="graph.gexf">Graf untuk Gephi (GEXF)</option><option value="result.json">Hasil lengkap (JSON)</option>` : ""}
        </select>
      </div>
    </div>
    <div class="tabs">${tabs.map(([k, l]) => `<button class="tab ${S.tab === k ? "active" : ""}" onclick="go('#/case/${c.id}/${k}')">${l}</button>`).join("")}</div>
    <div id="tabBody"></div>`;
  const body = $("#tabBody");
  if (S.tab !== "data" && !r) {
    body.innerHTML = `<div class="card empty">Belum ada hasil analisis.<br><br>
      ${c.n_posts ? `<button class="btn primary" onclick="openAnalyze()">Jalankan analisis</button>` : `<button class="btn" onclick="go('#/case/${c.id}/data')">Tambah data dulu</button>`}</div>`;
    return;
  }
  ({ data: tabData, ringkasan: tabSummary, narasi: tabNarr, penyebaran: tabSpread, jaringan: tabNetwork, hashtag: tabTags, akun: tabAccounts }[S.tab] || tabSummary)(body);
}

/* ---------------------------------------------------------------- beranda */
function viewHome(m) {
  m.innerHTML = `${menuBtn}
  <div style="max-width:760px">
    <h1>Telusuri dari mana sebuah isu berasal</h1>
    <p class="mut">Kumpulkan post, komentar, caption, dan berita dari berbagai platform. Tool ini memetakan narasi yang mirip,
    melacak siapa yang pertama memakai frasa khasnya, bagaimana isu melompat antar platform, dan pola akun yang menyebarkannya.</p>
    <div class="card" style="margin-top:18px">
      <h2>Kasus baru</h2>
      <div class="grid" style="gap:10px">
        <label class="f"><span>Nama kasus</span><input type="text" id="newName" placeholder="mis. Isu air PDAM tercemar"></label>
        <label class="f"><span>Catatan (opsional)</span><textarea id="newDesc" placeholder="Latar belakang, kata kunci awal, tautan pertama yang ditemukan…"></textarea></label>
        <div class="row"><button class="btn primary" onclick="createCase()">Buat kasus</button>
        <span class="mut small">atau</span><button class="btn" onclick="makeDemo(this)">Coba dengan data demo</button></div>
      </div>
    </div>
    <div class="grid g3" style="margin-top:14px">
      <div class="card flat"><h3>1. Kumpulkan</h3><div class="small mut">Google News, GDELT, X, TikTok, Reddit, Mastodon, Bluesky, atau unggah file ekspor (CSV/JSON) dari platform lain.</div></div>
      <div class="card flat"><h3>2. Analisis</h3><div class="small mut">Kemiripan makna, frasa khas, sikap, lompatan platform, pohon penyebaran, jaringan akun. Opsional: ringkasan oleh Claude.</div></div>
      <div class="card flat"><h3>3. Telusuri</h3><div class="small mut">Kandidat sumber beserta alasannya, kronologi, dan ekspor ke CSV/Gephi untuk verifikasi lanjutan.</div></div>
    </div>
  </div>`;
}
async function createCase() {
  const name = $("#newName").value.trim();
  if (!name) return toast("Isi nama kasus");
  const c = await api("/api/cases", { method: "POST", body: JSON.stringify({ name, description: $("#newDesc").value }) });
  go(`#/case/${c.id}/data`);
}
async function makeDemo(btn) {
  btn.disabled = true; btn.textContent = "Membuat demo…";
  const c = await api("/api/demo", { method: "POST" });
  S.caseId = null; go(`#/case/${c.id}/ringkasan`);
}

/* ---------------------------------------------------------------- tab: data */
function tabData(el) {
  const q = S.case.queries || {};
  const v = k => esc(Array.isArray(q[k]) ? q[k].join("; ") : (q[k] ?? ""));
  el.innerHTML = `
  <div class="grid g2">
    <div class="card">
      <h2>Kumpulkan otomatis</h2>
      <div class="small mut" style="margin-bottom:10px">Pisahkan beberapa kata kunci dengan titik koma (;). Sumber yang butuh token akan dilewati jika tokennya belum diisi di <a href="#" onclick="openSettings();return false">Pengaturan</a>.</div>
      <div class="form-grid">
        <label class="f"><span>Google News</span><input type="text" id="q_gnews" value="${v("gnews")}" placeholder="air pdam tercemar"></label>
        <label class="f"><span>GDELT (berita global)</span><input type="text" id="q_gdelt" value="${v("gdelt")}" placeholder="pdam tercemar"></label>
        <label class="f"><span>X: query</span><input type="text" id="q_x" value="${v("x")}" placeholder='#AirKotaTercemar OR "air pdam" lang:id'></label>
        <label class="f"><span>X: conversation_id thread</span><input type="text" id="q_x_thread" value="${v("x_thread")}" placeholder="1856…"></label>
        <label class="f"><span>TikTok: kata kunci</span><input type="text" id="q_tiktok" value="${v("tiktok")}"></label>
        <label class="f"><span>TikTok: hashtag (tanpa #)</span><input type="text" id="q_tiktok_tag" value="${v("tiktok_tag")}"></label>
        <label class="f"><span>Reddit</span><input type="text" id="q_reddit" value="${v("reddit")}"></label>
        <label class="f"><span>Mastodon: hashtag</span><input type="text" id="q_mastodon" value="${v("mastodon")}"></label>
        <label class="f"><span>Bluesky</span><input type="text" id="q_bluesky" value="${v("bluesky")}"></label>
        <label class="f"><span>Dari tanggal</span><input type="date" id="q_start_date" value="${v("start_date")}"></label>
        <label class="f"><span>Sampai tanggal</span><input type="date" id="q_end_date" value="${v("end_date")}"></label>
        <label class="f"><span>Maks. item per query</span><input type="number" id="q_max_items" value="${v("max_items") || 500}"></label>
      </div>
      <details style="margin-top:10px"><summary>Opsi lanjutan</summary>
        <div class="form-grid" style="margin-top:10px">
          <label class="f"><span>Bahasa GDELT</span><input type="text" id="q_gdelt_lang" value="${v("gdelt_lang") || "indonesian"}"></label>
          <label class="f"><span>Rentang GDELT (tanpa tanggal)</span><input type="text" id="q_timespan" value="${v("timespan") || "3m"}"></label>
          <label class="f"><span>Region TikTok</span><input type="text" id="q_tiktok_region" value="${v("tiktok_region")}" placeholder="ID"></label>
          <label class="f"><span>Komentar dari N video TikTok teratas</span><input type="number" id="q_comments_for_top" value="${v("comments_for_top") || 15}"></label>
          <label class="f"><span>Instance Mastodon</span><input type="text" id="q_mastodon_instance" value="${v("mastodon_instance") || "mastodon.social"}"></label>
          <div class="grid" style="gap:4px">
            <label class="chk"><input type="checkbox" id="q_x_archive" ${q.x_archive ? "checked" : ""}> X arsip penuh (paket Pro)</label>
            <label class="chk"><input type="checkbox" id="q_x_apify" ${q.x_apify ? "checked" : ""}> X lewat Apify</label>
            <label class="chk"><input type="checkbox" id="q_tiktok_apify" ${q.tiktok_apify ? "checked" : ""}> TikTok lewat Apify</label>
          </div>
        </div>
      </details>
      <div class="sep"></div>
      <div class="row spread"><h3 style="margin:0">TikTok lewat browser (Camoufox)</h3><span class="small" id="cfStatus"></span></div>
      <div class="small mut" style="margin:4px 0 10px">Membuka halaman TikTok seperti pengguna biasa dan membaca data yang dimuat halaman. Jeda acak antar langkah; berhenti bila TikTok meminta verifikasi. Atur proxy & login di <a href="#" onclick="openSettings();return false">Pengaturan</a>.</div>
      <label class="f"><span>Daftar target (satu per baris)</span>
        <textarea id="q_tt_b_targets" rows="6" placeholder="#airkotatercemar | 200
@lembahsari.viral
air pdam tercemar
https://www.tiktok.com/@akun/video/7311234567890123456 | 500">${esc(q.tt_b_targets || [..._lst(q.tt_b_tags).map(t => "#" + t.replace(/^#/, "")), ..._lst(q.tt_b_keywords), ..._lst(q.tt_b_urls)].join("\n"))}</textarea>
        <span><code>#hashtag</code> · <code>@akun</code> · kata kunci (pencarian) · URL video / hashtag / pencarian / profil TikTok. Tambahkan <code>| angka</code> untuk batas per target: jumlah video, atau jumlah komentar untuk URL video.</span></label>
      <div class="form-grid" style="margin-top:10px">
        <label class="f"><span>Batas video per target (bawaan)</span><input type="number" id="q_tt_b_max_videos" value="${v("tt_b_max_videos") || 100}"></label>
        <label class="f"><span>Batas komentar per video (bawaan)</span><input type="number" id="q_tt_b_max_comments" value="${v("tt_b_max_comments") || 300}"></label>
        <label class="f"><span>Ambil juga komentar dari N video teratas</span><input type="number" id="q_tt_b_comments_top" value="${v("tt_b_comments_top") || 10}"></label>
        <div class="grid" style="gap:4px;align-content:end">
          <label class="chk"><input type="checkbox" id="q_tt_b_replies" ${q.tt_b_replies === false ? "" : "checked"}> Buka balasan komentar</label>
          <label class="chk"><input type="checkbox" id="q_tt_b_show_browser" ${q.tt_b_show_browser ? "checked" : ""}> Tampilkan jendela browser</label>
        </div>
      </div>
      <div class="row" style="margin-top:12px"><button class="btn primary" onclick="startCollect(this)">Mulai kumpulkan</button></div>
    </div>
    <div class="card">
      <h2>Unggah file</h2>
      <div class="small mut" style="margin-bottom:10px">CSV, JSON, atau JSONL dari scraper/ekspor apa pun (X, TikTok, Instagram, Facebook, YouTube, WhatsApp yang disalin ke spreadsheet, dsb.). Kolom teks, waktu, dan akun dikenali otomatis. Format X API, Apify, dan TikTok Research dikenali langsung.</div>
      <div class="drop" id="drop">Seret file ke sini atau <a href="#" onclick="$('#file').click();return false">pilih file</a><input type="file" id="file" accept=".csv,.json,.jsonl" hidden multiple></div>
      <div class="form-grid" style="margin-top:10px">
        <label class="f"><span>Platform (jika tidak ada kolom platform)</span>
          <select id="upPlat"><option value="">otomatis</option>${PLAT_ORDER.map(p => `<option value="${p}">${PLAT_LABEL[p]}</option>`).join("")}<option value="whatsapp">WhatsApp</option><option value="telegram">Telegram</option></select></label>
        <label class="f"><span>Pemetaan kolom (opsional)</span><input type="text" id="upMap" placeholder="text=isi, created_at=waktu, author=akun"></label>
      </div>
      <div class="sep"></div>
      <h3>Aktivitas</h3>
      <div id="jobs">${(S.case.jobs || []).slice(0, 4).map(j => jobHtml(j)).join("") || `<div class="mut small">Belum ada.</div>`}</div>
    </div>
  </div>
  <div class="card" style="margin-top:14px">
    <div class="row spread"><h2 style="margin:0">Data terkumpul</h2>
      <div class="row"><input type="text" id="pq" placeholder="Cari teks/akun…" style="width:220px" oninput="clearTimeout(window._pt);window._pt=setTimeout(loadPosts,300)">
      <select id="pplat" onchange="loadPosts()"><option value="">Semua platform</option>${Object.keys(S.case.platforms || {}).map(p => `<option value="${p}">${PLAT_LABEL[p] || p}</option>`).join("")}</select>
      <button class="btn sm danger" onclick="clearPosts()">Hapus data</button></div></div>
    <div class="tw" id="postTable" style="margin-top:10px"></div>
  </div>`;
  const drop = $("#drop"), file = $("#file");
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); uploadFiles(e.dataTransfer.files); };
  file.onchange = () => uploadFiles(file.files);
  loadPosts();
  api("/api/camoufox/status").then(c => { const el = $("#cfStatus"); if (!el) return;
    el.innerHTML = !c.installed ? `<span class="chip warn">Camoufox belum terpasang</span>`
      : `${c.proxy ? `<span class="chip">proxy: ${esc(c.proxy)}</span>` : `<span class="chip warn">tanpa proxy (IP Anda terlihat)</span>`}${c.profile ? `<span class="chip">profil tersimpan</span>` : `<span class="chip">belum login</span>`}`; });
  (S.case.jobs || []).filter(j => j.status === "running").forEach(j => pollJob(j.id));
}
function jobHtml(j) {
  const label = { collect: "Pengumpulan", analyze: "Analisis" }[j.kind] || j.kind;
  const st = { running: `<span class="chip acc">berjalan…</span>`, done: `<span class="chip">selesai</span>`, error: `<span class="chip warn">gagal</span>` }[j.status];
  return `<div id="job_${j.id}" style="margin-bottom:10px"><div class="row small"><b>${label}</b> ${st} <span class="mut">${fmt(j.created * 1000)}</span></div>
    ${j.log ? `<div class="log" style="margin-top:6px">${esc(j.log.trim().split("\n").slice(-30).join("\n"))}</div>` : ""}</div>`;
}
function collectForm() {
  const q = {};
  for (const k of ["gnews", "gdelt", "x", "x_thread", "tiktok", "tiktok_tag", "reddit", "mastodon", "bluesky", "start_date", "end_date", "max_items", "gdelt_lang", "timespan", "tiktok_region", "comments_for_top", "mastodon_instance", "tt_b_targets", "tt_b_max_videos", "tt_b_comments_top", "tt_b_max_comments"]) q[k] = $("#q_" + k).value.trim();
  for (const k of ["x_archive", "x_apify", "tiktok_apify", "tt_b_show_browser", "tt_b_replies"]) q[k] = $("#q_" + k).checked;
  return q;
}
async function startCollect(btn) {
  const q = collectForm();
  if (!["gnews", "gdelt", "x", "x_thread", "tiktok", "tiktok_tag", "reddit", "mastodon", "bluesky", "tt_b_targets"].some(k => q[k])) return toast("Isi minimal satu sumber");
  btn.disabled = true;
  const { job } = await api(`/api/cases/${S.caseId}/collect`, { method: "POST", body: JSON.stringify(q) });
  S.case.queries = q;
  $("#jobs").insertAdjacentHTML("afterbegin", jobHtml({ id: job, kind: "collect", status: "running", created: Date.now() / 1000, log: "" }));
  pollJob(job, async () => { btn.disabled = false; await loadCase(); await loadCases(); render(); });
}
async function uploadFiles(files) {
  for (const f of files) {
    const fd = new FormData(); fd.append("file", f); fd.append("platform", $("#upPlat").value); fd.append("mapping", $("#upMap").value);
    try {
      const r = await api(`/api/cases/${S.caseId}/upload`, { method: "POST", body: fd });
      toast(`${f.name}: ${r.read} baris dibaca, ${r.added} baru${r.no_time ? `, ${r.no_time} tanpa waktu (diabaikan saat analisis)` : ""}`);
    } catch (e) { toast(`${f.name}: ${e.message}`); }
  }
  await loadCase(); await loadCases(); render();
}
async function loadPosts(offset = 0) {
  const q = encodeURIComponent($("#pq")?.value || ""), p = $("#pplat")?.value || "";
  const { total, rows } = await api(`/api/cases/${S.caseId}/posts?q=${q}&platform=${p}&offset=${offset}&limit=50`);
  const el = $("#postTable"); if (!el) return;
  el.innerHTML = total ? `<table><tr><th>Waktu</th><th>Platform</th><th>Jenis</th><th>Akun</th><th>Teks</th><th class="num">Engagement</th></tr>
    ${rows.map(r => `<tr><td class="small">${fmt(r.created_at)}</td><td>${pill(r.platform)}</td><td class="small">${esc(r.kind)}</td><td>${esc(r.author)}</td><td class="txt">${link(r.url, r.text.slice(0, 260))}</td><td class="num">${num(r.engagement)}</td></tr>`).join("")}</table>
    <div class="row small mut" style="margin-top:8px">${offset + 1}–${Math.min(offset + 50, total)} dari ${num(total)}
      ${offset ? `<button class="btn sm" onclick="loadPosts(${offset - 50})">‹ Sebelumnya</button>` : ""}
      ${offset + 50 < total ? `<button class="btn sm" onclick="loadPosts(${offset + 50})">Berikutnya ›</button>` : ""}</div>`
    : `<div class="empty">Belum ada data. Kumpulkan otomatis atau unggah file di atas.</div>`;
}
async function clearPosts() {
  const p = $("#pplat").value;
  if (!confirm(p ? `Hapus semua post ${PLAT_LABEL[p] || p}?` : "Hapus semua post di kasus ini?")) return;
  await api(`/api/cases/${S.caseId}/posts${p ? "?platform=" + p : ""}`, { method: "DELETE" });
  await loadCase(); await loadCases(); render();
}
function pollJob(jid, done) {
  if (S.jobs[jid]) return; S.jobs[jid] = true;
  const tick = async () => {
    const j = await api(`/api/jobs/${jid}`);
    const el = $("#job_" + jid); if (el) el.outerHTML = jobHtml(j);
    const ael = $("#anLog"); if (ael && j.kind === "analyze") { ael.textContent = j.log.trim().split("\n").slice(-30).join("\n"); ael.scrollTop = 1e6; }
    if (j.status === "running") return setTimeout(tick, 1200);
    delete S.jobs[jid];
    if (j.status === "error") toast("Job gagal, lihat log");
    done && done(j);
  };
  tick();
}

/* ---------------------------------------------------------------- analisis */
async function openAnalyze() {
  const st = await api("/api/settings");
  const p = S.result?.params || {};
  const val = (k, d) => p[k] ?? d;
  modal(`<h2>Analisis</h2>
    <div class="small mut" style="margin-bottom:12px">Ambang yang lebih rendah menghubungkan lebih banyak post (lebih peka, tapi lebih banyak tautan palsu).</div>
    <div class="form-grid">
      <label class="f"><span>Filter kata kunci (pisah koma)</span><input type="text" id="a_kw" value="${esc((p.keyword_filter || []).join(", "))}"></label>
      <label class="f"><span>Ambang salinan teks (0–1)</span><input type="number" step="0.05" id="a_copy" value="${val("copy_threshold", 0.5)}"></label>
      <label class="f"><span>Ambang tautan narasi (0–1)</span><input type="number" step="0.05" id="a_link" value="${val("link_threshold", 0.25)}"></label>
      <label class="f"><span>Ambang kelompok narasi (0–1)</span><input type="number" step="0.05" id="a_cluster" value="${val("cluster_threshold", 0.25)}"></label>
      <label class="f"><span>Ukuran minimal narasi</span><input type="number" id="a_min" value="${val("min_narrative", 3)}"></label>
      <label class="f"><span>Koordinasi: jendela (menit)</span><input type="number" id="a_cw" value="${val("coord_window_min", 10)}"></label>
      <label class="f"><span>Koordinasi: minimal akun</span><input type="number" id="a_ca" value="${val("coord_min_accounts", 4)}"></label>
      <label class="f"><span>Jaringan akun: jendela (menit)</span><input type="number" id="a_nw" value="${val("network_window_min", 30)}"></label>
    </div>
    <div class="sep"></div>
    <label class="chk"><input type="checkbox" id="a_llm" ${st.keys.ANTHROPIC_API_KEY.set ? "checked" : "disabled"}>
      Ringkas & nilai narasi dengan Claude (${esc(st.llm_model)})</label>
    <div class="small mut" style="margin:4px 0 0 22px">${st.keys.ANTHROPIC_API_KEY.set ? "Mengirim sampel teks narasi teratas (maks. 8 narasi) ke Anthropic API. Ada biaya per pemakaian." : "Isi ANTHROPIC_API_KEY di Pengaturan untuk mengaktifkan."}</div>
    <div class="log" id="anLog" style="margin-top:12px;display:none"></div>
    <div class="row" style="margin-top:14px;justify-content:flex-end"><button class="btn" onclick="closeModal()">Tutup</button><button class="btn primary" id="anBtn" onclick="runAnalyze()">Jalankan</button></div>`);
}
async function runAnalyze() {
  const body = { keyword_filter: $("#a_kw").value, copy_threshold: $("#a_copy").value, link_threshold: $("#a_link").value, cluster_threshold: $("#a_cluster").value, min_narrative: $("#a_min").value, coord_window_min: $("#a_cw").value, coord_min_accounts: $("#a_ca").value, network_window_min: $("#a_nw").value, use_llm: $("#a_llm").checked };
  $("#anBtn").disabled = true; $("#anLog").style.display = "block"; $("#anLog").textContent = "Memulai…";
  const { job } = await api(`/api/cases/${S.caseId}/analyze`, { method: "POST", body: JSON.stringify(body) });
  pollJob(job, async j => {
    if (j.status !== "done") { $("#anBtn").disabled = false; return; }
    closeModal(); await loadCase(); await loadCases(); S.narr = null;
    go(`#/case/${S.caseId}/ringkasan`); render(); toast("Analisis selesai");
  });
}

/* ---------------------------------------------------------------- tab: ringkasan */
function tabSummary(el) {
  const r = S.result, s = r.summary, o = r.llm_overall;
  const topN = r.narratives[0];
  const firstSrc = r.origin_candidates[0];
  el.innerHTML = `
  ${o ? `<div class="hl" style="margin-bottom:14px"><div class="row spread"><h2>${esc(o.headline)}</h2><span class="chip acc">Claude · keyakinan ${esc(o.confidence)}</span></div>
    <div class="grid g2" style="margin-top:6px"><div><b class="small">Kronologi</b><div>${esc(o.origin_story)}</div></div>
    <div><b class="small">Sumber paling mungkin</b><div>${esc(o.most_likely_source)}</div><b class="small" style="display:block;margin-top:8px">Pola penyebaran</b><div>${esc(o.amplification_pattern)}</div></div></div>
    ${o.gaps?.length ? `<div class="small mut" style="margin-top:8px"><b>Celah data:</b> ${o.gaps.map(esc).join(" · ")}</div>` : ""}</div>` : ""}
  <div class="kpis">
    ${[["Post", s.posts], ["Akun", s.authors], ["Platform", Object.keys(s.platforms).length], ["Narasi", s.narratives], ["Pola koordinasi", s.coordination_flags], ["Jaringan akun", s.networks || 0]]
      .map(([k, v]) => `<div class="kpi"><span>${k}</span><b>${num(v)}</b></div>`).join("")}
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card">
      <h2>Kandidat sumber awal</h2>
      <div class="small mut" style="margin-bottom:6px">Post yang tidak punya induk di data, diurutkan menurut jangkauan penyebaran, sebaran platform, dan seberapa awal.</div>
      ${r.origin_candidates.slice(0, 6).map((c, i) => `
        <div class="src-card"><div class="meter"><b>${i + 1}</b><span class="small mut">${num(c.cascade_size)} post</span></div>
        <div style="min-width:0">${pill(c.platform)} <b>${esc(c.author)}</b> <span class="small mut">${fmt(c.time)}</span>
          ${c.narrative ? `<a class="chip acc" href="#/case/${S.caseId}/narasi" onclick="S.narr='${c.narrative}'">${c.narrative}</a>` : ""}
          <div class="txt" style="margin:3px 0">${link(c.url, c.text)}</div>
          <div>${c.reasons.map(x => `<span class="chip">${esc(x)}</span>`).join("")}</div></div></div>`).join("")}
    </div>
    <div class="grid" style="gap:14px;align-content:start">
      <div class="card"><h2>Kemunculan pertama per platform</h2>
        <div class="timeline-v">${Object.entries(s.first_by_platform).sort((a, b) => a[1].time < b[1].time ? -1 : 1).map(([p, x]) => `
          <div class="tl-item" style="--dot:${platColor(p)}"><div class="row small">${pill(p)} <b>${esc(x.author)}</b> <span class="mut">${fmt(x.time)}</span></div>
          <div class="small txt">${link(x.url, x.text.slice(0, 160))}</div></div>`).join("")}</div></div>
      <div class="card"><h2>Sikap seluruh post</h2>${stanceBar(s.stance)}</div>
    </div>
  </div>
  <div class="card" style="margin-top:14px"><div class="row spread"><h2 style="margin:0">Volume per jam</h2>
    <div class="legend">${Object.keys(s.platforms).map(p => `<span><i style="background:${platColor(p)}"></i>${PLAT_LABEL[p] || p}</span>`).join("")}</div></div>
    <div id="tl" style="margin-top:10px"></div></div>
  <div class="card" style="margin-top:14px"><h2>Narasi utama</h2>
    <div class="tw"><table><tr><th></th><th>Klaim / teks representatif</th><th class="num">Post</th><th class="num">Akun</th><th>Mulai</th><th>Sumber terkuat</th><th>Sikap</th></tr>
    ${r.narratives.slice(0, 8).map(n => `<tr class="click" onclick="S.narr='${n.id}';go('#/case/${S.caseId}/narasi')">
      <td><b>${n.id}</b></td><td class="txt">${esc(n.llm?.claim || n.representative.text.slice(0, 180))}</td><td class="num">${n.size}</td><td class="num">${n.authors}</td>
      <td class="small">${fmt(n.first.time)}</td><td>${n.source_attribution[0] ? `${pill(n.source_attribution[0].platform)} ${esc(n.source_attribution[0].author)}` : ""}</td>
      <td style="min-width:110px">${stanceBar(n.stance, true)}</td></tr>`).join("") || `<tr><td colspan=7 class="mut">Tidak ada narasi dengan ≥ ${r.params.min_narrative} post.</td></tr>`}</table></div></div>
  <div class="card flat" style="margin-top:14px"><div class="small mut"><b>Keterbatasan.</b> "Paling awal" artinya paling awal <b>di data yang terkumpul</b>. Post yang dihapus, akun privat, grup tertutup (WhatsApp/Telegram/FB Group), batas API, dan rentang pencarian bisa menyembunyikan sumber sebenarnya. Tautan selain balasan/repost/quote adalah dugaan berbasis kemiripan. Verifikasi manual (arsip Wayback/archive.today, reverse image search, konfirmasi ke sumber) tetap diperlukan sebelum menyimpulkan.</div></div>`;
  drawTimeline($("#tl"), r.timeline, Object.keys(s.platforms));
}
function stanceBar(st, compact) {
  const tot = Object.values(st || {}).reduce((a, b) => a + b, 0) || 1;
  const bar = `<div class="stbar">${STANCES.filter(k => st[k]).map(k => `<i title="${k}: ${st[k]}" style="width:${st[k] / tot * 100}%;background:${stColor(k)}"></i>`).join("")}</div>`;
  if (compact) return bar;
  return bar + `<div class="legend" style="margin-top:8px">${STANCES.filter(k => st[k]).map(k => `<span><i style="background:${stColor(k)}"></i>${k} ${st[k]} (${Math.round(st[k] / tot * 100)}%)</span>`).join("")}</div>`;
}
function drawTimeline(el, T, plats, h = 200) {
  if (!T.length) { el.innerHTML = `<div class="mut small">Tidak ada data.</div>`; return; }
  const W = el.clientWidth || 800, P = { l: 34, r: 8, t: 8, b: 22 };
  const t0 = new Date(T[0].hour).getTime(), t1 = new Date(T[T.length - 1].hour).getTime();
  const hours = Math.max(1, Math.round((t1 - t0) / 36e5) + 1);
  const bucket = Math.max(1, Math.ceil(hours / 120));            // maksimal ~120 batang
  const bins = Array.from({ length: Math.ceil(hours / bucket) }, (_, i) => ({ t: t0 + i * bucket * 36e5, v: {} }));
  T.forEach(r => { const i = Math.floor((new Date(r.hour).getTime() - t0) / 36e5 / bucket); plats.forEach(p => { if (r[p]) bins[i].v[p] = (bins[i].v[p] || 0) + r[p]; }); });
  const max = Math.max(1, ...bins.map(b => Object.values(b.v).reduce((a, c) => a + c, 0)));
  const bw = (W - P.l - P.r) / bins.length, ih = h - P.t - P.b;
  let s = `<line x1="${P.l}" x2="${W - P.r}" y1="${h - P.b}" y2="${h - P.b}" stroke="${css("--line2")}"/>`;
  [0.5, 1].forEach(f => { const y = h - P.b - f * ih; s += `<line x1="${P.l}" x2="${W - P.r}" y1="${y}" y2="${y}" stroke="${css("--line")}" stroke-dasharray="2 3"/><text x="${P.l - 6}" y="${y + 4}" font-size="10" text-anchor="end" opacity=".6">${Math.round(max * f)}</text>`; });
  bins.forEach((b, i) => {
    let y = h - P.b;
    plats.forEach(p => { const v = b.v[p]; if (!v) return; const hh = v / max * ih; y -= hh;
      s += `<rect x="${P.l + i * bw + 0.5}" y="${y}" width="${Math.max(1, bw - 1)}" height="${hh}" fill="${platColor(p)}" rx="1"><title>${fmtShort(b.t)} · ${PLAT_LABEL[p] || p}: ${v}</title></rect>`; });
  });
  const step = Math.ceil(bins.length / Math.max(2, Math.floor(W / 110)));
  bins.forEach((b, i) => { if (i % step === 0) s += `<text x="${P.l + i * bw}" y="${h - 6}" font-size="10" opacity=".6">${new Date(b.t).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit" })}</text>`; });
  el.innerHTML = `<svg width="100%" viewBox="0 0 ${W} ${h}" style="display:block">${s}</svg>`;
}

/* ---------------------------------------------------------------- tab: narasi */
function tabNarr(el) {
  const N = S.result.narratives;
  if (!N.length) { el.innerHTML = `<div class="card empty">Tidak ada narasi dengan ≥ ${S.result.params.min_narrative} post. Coba turunkan ambang kelompok narasi saat analisis.</div>`; return; }
  if (!S.narr || !N.find(n => n.id === S.narr)) S.narr = N[0].id;
  el.innerHTML = `<div class="narr-layout"><div class="narr-list">${N.map(n => `
    <div class="narr-item ${n.id === S.narr ? "active" : ""}" onclick="S.narr='${n.id}';render()">
      <div class="row spread small"><b>${n.id}</b><span class="mut">${n.size} post · ${n.authors} akun</span></div>
      <div class="t">${esc(n.llm?.claim || n.representative.text)}</div>
      ${stanceBar(n.stance, true)}
      <div class="small mut" style="margin-top:6px">${fmt(n.first.time)} · ${Object.keys(n.platforms).map(p => PLAT_LABEL[p] || p).join(", ")}</div>
    </div>`).join("")}</div><div id="narrDetail"></div></div>`;
  narrDetail($("#narrDetail"), N.find(n => n.id === S.narr));
}
function narrDetail(el, n) {
  const L = n.llm;
  const coord = S.result.coordination.filter(c => c.narrative === n.id);
  el.innerHTML = `
  <div class="card">
    <div class="row spread"><h2 style="margin:0">Narasi ${n.id}</h2>
      <div class="row"><span class="small mut">${n.size} post · ${n.authors} akun · ${n.n_variants} varian teks · ${n.duration_hours} jam</span>
      <button class="btn sm" onclick="S.graphNarr='${n.id}';go('#/case/${S.caseId}/penyebaran')">Lihat graf</button></div></div>
    ${L ? `<div class="hl" style="margin-top:12px"><div class="row spread"><b>${esc(L.claim)}</b><span class="chip acc">Claude · keyakinan ${esc(L.confidence)}</span></div>
      <div style="margin-top:6px">${esc(L.summary)}</div>
      <div class="grid g2" style="margin-top:10px;gap:10px">
        <div class="small"><b>Framing:</b> ${esc(L.framing)}<br><b>Nada:</b> ${esc(L.emotional_tone)}<br><b>Aktor disebut:</b> ${L.actors.map(esc).join(", ") || "–"}</div>
        <div class="small"><b>Penilaian sumber:</b> ${esc(L.origin_assessment)}<br><b>Evolusi teks:</b> ${esc(L.evolution)}</div>
      </div>
      ${L.manipulation_signals.length ? `<div style="margin-top:8px">${L.manipulation_signals.map(x => `<span class="flag">${esc(x)}</span>`).join("")}</div>` : ""}
      ${L.verification_steps.length ? `<details style="margin-top:8px"><summary>Langkah verifikasi yang disarankan</summary><ul class="small">${L.verification_steps.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>` : ""}
    </div>` : `<div style="margin-top:10px"><div class="small mut">Teks paling representatif</div><div>${link(n.representative.url, n.representative.text)}</div></div>`}
    <div class="grid g3" style="margin-top:14px;gap:12px">
      <div><div class="small mut">Istilah kunci</div>${n.key_terms.map(t => `<span class="chip">${esc(t)}</span>`).join("")}</div>
      <div><div class="small mut">Hashtag</div>${n.hashtags.map(t => `<span class="chip">#${esc(t)}</span>`).join("") || "–"}</div>
      <div><div class="small mut">Sikap</div>${stanceBar(n.stance)}</div>
    </div>
    <div class="small mut" style="margin-top:10px">Gaya: ${n.style.urgency_posts} post bernada mendesak/ajakan, ${n.style.emoji_posts} pakai emoji, rata-rata huruf kapital ${Math.round(n.style.avg_caps * 100)}%.</div>
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h2>Kemungkinan sumber</h2>
      <div class="small mut" style="margin-bottom:6px">Skor gabungan: seberapa awal, berapa post yang diturunkan, dan siapa yang pertama memakai frasa khas narasi ini.</div>
      ${n.source_attribution.map((a, i) => `<div class="src-card"><div class="meter"><b>${Math.round((a.share || 0) * 100)}%</b><span class="small mut">bobot</span></div>
        <div style="min-width:0">${pill(a.platform)} <b>${esc(a.author)}</b> <span class="small mut">${fmt(a.first_time)}</span>
        <div>${a.reasons.map(x => `<span class="chip">${esc(x)}</span>`).join("")}</div></div></div>`).join("")}
    </div>
    <div class="card"><h2>Lompatan antar platform</h2>
      <div class="timeline-v">${n.platform_jumps.map(j => `<div class="tl-item" style="--dot:${platColor(j.platform)}">
        <div class="row small">${pill(j.platform)} <b>${esc(j.author)}</b> <span class="mut">${fmt(j.time)}${j.delay_hours ? ` · +${j.delay_hours < 1 ? Math.round(j.delay_hours * 60) + " menit" : j.delay_hours + " jam"}` : " · titik awal"}</span></div>
        <div class="small txt">${esc(j.text)}</div></div>`).join("")}</div>
    </div>
  </div>
  <div class="card" style="margin-top:14px"><h2>Frasa khas (sidik jari teks)</h2>
    <div class="small mut" style="margin-bottom:6px">Rangkaian kata yang berulang di narasi ini tapi jarang di luar narasi. Siapa yang pertama memakainya adalah petunjuk kuat asal teks.</div>
    <div class="tw"><table><tr><th>Frasa</th><th class="num">Post</th><th class="num">Akun</th><th class="num">Kekhasan</th><th>Pertama dipakai oleh</th><th>Waktu</th></tr>
    ${n.signature_phrases.map(f => `<tr><td><b>"${esc(f.phrase)}"</b></td><td class="num">${f.posts}</td><td class="num">${f.authors}</td><td class="num">${Math.round(f.specificity * 100)}%</td><td>${pill(f.first_platform)} ${esc(f.first_author)}</td><td class="small">${fmt(f.first_time)}</td></tr>`).join("") || `<tr><td colspan=6 class="mut">Tidak ada frasa berulang.</td></tr>`}</table></div>
  </div>
  <div class="card" style="margin-top:14px"><h2>Mutasi teks</h2>
    <div class="small mut" style="margin-bottom:6px">Varian teks berurutan waktu, dibandingkan dengan varian pertama. <span class="diff-add">Hijau</span> = kata baru, <span class="diff-del">coret</span> = kata yang hilang.</div>
    <div class="timeline-v">${n.variants.map((v, i) => `<div class="tl-item" style="--dot:${platColor(v.platform)}">
      <div class="row small">${pill(v.platform)} <b>${esc(v.author)}</b> <span class="mut">${fmt(v.time)}</span>${v.copies > 1 ? `<span class="chip warn">disalin ${v.copies}×</span>` : ""}</div>
      <div class="txt">${esc(v.text)}</div>
      ${i ? `<div class="small">${v.added.map(w => `<span class="diff-add">+${esc(w)}</span>`).join(" ")} ${v.removed.map(w => `<span class="diff-del">${esc(w)}</span>`).join(" ")}</div>` : ""}</div>`).join("")}</div>
  </div>
  ${coord.length ? `<div class="card" style="margin-top:14px;border-color:var(--warn)"><h2>Pola koordinasi</h2>${coord.map(coordHtml).join("")}</div>` : ""}
  <div class="card" style="margin-top:14px"><h2>Volume narasi</h2><div id="narrTl"></div></div>`;
  const plats = Object.keys(n.platforms);
  const byHour = {}; n.ids.forEach(id => { const nd = S.result.graph.nodes.find(x => x.id === id); if (!nd) return; const h = nd.time.slice(0, 13) + ":00:00"; byHour[h] = byHour[h] || {}; byHour[h][nd.platform] = (byHour[h][nd.platform] || 0) + 1; });
  drawTimeline($("#narrTl"), Object.entries(byHour).sort().map(([hour, v]) => ({ hour, ...v })), plats, 150);
}
function coordHtml(c) {
  return `<div style="padding:8px 0;border-bottom:1px solid var(--line)">
    <div class="row small"><b>${c.n_accounts} akun dalam ${c.minutes} menit</b> <span class="mut">${fmt(c.start)} – ${fmtShort(c.end)}</span> ${plist(c.platforms)}
    ${c.narrative ? `<a class="chip acc" href="#/case/${S.caseId}/narasi" onclick="S.narr='${c.narrative}'">${c.narrative}</a>` : ""}</div>
    <div class="small">${c.accounts.map(a => `<span class="chip">${esc(a)}</span>`).join("")}</div>
    <div class="small mut">${c.text_variants} varian teks berbeda · ${c.identical_hashtag_sets} post dengan susunan hashtag identik · ${esc(c.narrative_first)}</div></div>`;
}

/* ---------------------------------------------------------------- tab: graf penyebaran */
function tabSpread(el) {
  const r = S.result, N = r.narratives;
  const plats = Object.keys(r.summary.platforms);
  el.innerHTML = `
  <div class="row" style="margin-bottom:10px">
    <select id="gN" style="width:auto"><option value="">Semua narasi (cascade terbesar)</option>${N.map(n => `<option value="${n.id}" ${S.graphNarr === n.id ? "selected" : ""}>${n.id}: ${esc((n.llm?.claim || n.representative.text).slice(0, 60))}</option>`).join("")}</select>
    <select id="gLayout" style="width:auto"><option value="time">Tata letak: urutan waktu</option><option value="force">Tata letak: gaya</option></select>
    <label class="chk"><input type="checkbox" id="gSure"> Hanya tautan pasti</label>
    <label class="chk"><input type="checkbox" id="gComments" checked> Tampilkan komentar</label>
  </div>
  <div class="legend" style="margin-bottom:8px">${plats.map(p => `<span><i style="background:${platColor(p)}"></i>${PLAT_LABEL[p] || p}</span>`).join("")}
    <span>★ = akar (tidak ada induk)</span><span>— pasti (reply/repost/quote) · - - dugaan (kemiripan)</span></div>
  <div class="net" id="net"></div>
  <div class="small mut" id="gAxis" style="text-align:center;margin-top:4px"></div>
  <div class="card" id="gDetail" style="margin-top:10px"><span class="mut small">Klik node untuk detail. Ukuran node = jumlah post turunan.</span></div>`;
  ["gN", "gLayout", "gSure", "gComments"].forEach(id => $("#" + id).onchange = () => { S.graphNarr = $("#gN").value; drawSpread(); });
  drawSpread();
}
function drawSpread() {
  const r = S.result, G = r.graph, nid = $("#gN").value, sure = $("#gSure").checked, comments = $("#gComments").checked;
  const parent = Object.fromEntries(G.edges.map(e => [e.to, e]));
  const rootOf = id => { let i = id, k = 0; while (parent[i] && k++ < 1e4) i = parent[i].from; return i; };
  let nodes;
  if (nid) {
    const ids = new Set(r.narratives.find(n => n.id === nid).ids);
    nodes = G.nodes.filter(n => ids.has(n.id) || ids.has(parent[n.id]?.from) || n.narrative === nid);
  } else {
    const roots = new Set(); let total = 0;
    for (const o of r.origin_candidates) { if (total > 450) break; roots.add(o.id); total += o.cascade_size; }
    nodes = G.nodes.filter(n => roots.has(rootOf(n.id)));
  }
  if (!comments) nodes = nodes.filter(n => !["comment", "reply"].includes(n.kind) || n.desc > 0);
  const ids = new Set(nodes.map(n => n.id));
  const edges = G.edges.filter(e => ids.has(e.from) && ids.has(e.to) && (!sure || ["reply", "comment", "repost", "quote"].includes(e.reason)));
  const fg = css("--fg"), timeL = $("#gLayout").value === "time";
  const ts = nodes.map(n => new Date(n.time).getTime()), t0 = Math.min(...ts), t1 = Math.max(...ts);
  const span = Math.max(1, t1 - t0), pos = {};
  if (timeL) {   // sumbu X = waktu, satu jalur per cascade (diurutkan dari akar paling awal)
    const lanes = {};
    nodes.forEach(n => (lanes[rootOf(n.id)] = lanes[rootOf(n.id)] || []).push(n));
    let y = 0;
    Object.values(lanes).sort((a, b) => a[0].time < b[0].time ? -1 : 1).forEach(lane => {
      lane.sort((a, b) => a.time < b.time ? -1 : 1);
      const rows = Math.min(6, lane.length);
      lane.forEach((n, i) => { pos[n.id] = { x: (new Date(n.time).getTime() - t0) / span * 1800, y: y + (i % rows) * 26 }; });
      y += rows * 26 + 50;
    });
  }
  const vn = new vis.DataSet(nodes.map(n => ({
    id: n.id, label: (n.root && n.desc > 0) || n.desc >= 3 ? n.author : "", shape: n.root ? "star" : "dot",
    size: 7 + Math.sqrt(n.desc) * 4, color: { background: platColor(n.platform), border: n.stance === "membantah" ? stColor("membantah") : platColor(n.platform) },
    borderWidth: n.stance === "membantah" ? 3 : 1, font: { color: fg, size: 11 }, ...(pos[n.id] || {}),
    title: `${PLAT_LABEL[n.platform] || n.platform} · ${n.author}\n${fmt(n.time)}\n${n.text.slice(0, 160)}`
  })));
  const ve = new vis.DataSet(edges.map((e, i) => ({ id: i, from: e.from, to: e.to, arrows: { to: { scaleFactor: .5 } },
    dashes: !["reply", "repost", "quote", "comment"].includes(e.reason), color: { color: css("--mut"), opacity: .45 },
    smooth: timeL ? { type: "curvedCW", roundness: .15 } : true, title: `${REASON[e.reason] || e.reason} (${e.conf})` })));
  const opts = timeL ? { physics: false } : { physics: { solver: "forceAtlas2Based", stabilization: { iterations: 200 } } };
  const net = new vis.Network($("#net"), { nodes: vn, edges: ve }, { ...opts, interaction: { hover: true, tooltipDelay: 120 } });
  if (timeL) { net.once("afterDrawing", () => net.fit()); $("#gAxis").textContent = `← ${fmt(t0)}   ·   waktu   ·   ${fmt(t1)} →`; } else $("#gAxis").textContent = "";
  const byId = Object.fromEntries(G.nodes.map(n => [n.id, n]));
  net.on("click", ev => {
    const n = byId[ev.nodes[0]]; if (!n) return;
    const pe = parent[n.id], kids = G.edges.filter(e => e.from === n.id);
    $("#gDetail").innerHTML = `<div class="row small">${pill(n.platform)} <b>${esc(n.author)}</b> <span class="mut">${fmt(n.time)} · ${esc(n.kind)}</span> ${stPill(n.stance)}
      ${n.narrative ? `<span class="chip acc">${n.narrative}</span>` : ""}<span class="mut">turunan: ${n.desc}</span></div>
      <div class="txt" style="margin:6px 0">${link(n.url, n.text)}</div>
      <div class="small mut">${pe ? `Induk (${REASON[pe.reason] || pe.reason}, ${pe.conf}): <b>${esc(byId[pe.from]?.author)}</b> · ${fmt(byId[pe.from]?.time)} · ${esc(byId[pe.from]?.text.slice(0, 120))}` : "Akar: tidak ditemukan induk di data."}
      ${kids.length ? `<br>Menyebar langsung ke ${kids.length} post: ${[...new Set(kids.map(k => byId[k.to]?.author))].slice(0, 12).map(esc).join(", ")}` : ""}</div>`;
  });
}

/* ---------------------------------------------------------------- tab: jaringan & koordinasi */
function tabNetwork(el) {
  const r = S.result, net = r.account_network;
  el.innerHTML = `
  <div class="card"><h2>Jaringan akun</h2>
    <div class="small mut" style="margin-bottom:8px">Akun dihubungkan bila berulang kali memposting narasi yang sama dalam ${r.params.network_window_min} menit. Kelompok yang rapat dan aktif di beberapa narasi bisa menandakan amplifikasi terorganisir. Ini indikasi, bukan bukti.</div>
    ${net.nodes.length ? `<div class="net" id="accNet" style="height:460px"></div>` : `<div class="empty">Tidak ada pasangan akun yang berulang kali memposting berdekatan.</div>`}
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h2>Kelompok akun</h2>${net.communities.map((c, i) => `<div style="padding:8px 0;border-bottom:1px solid var(--line)">
      <div class="row small"><span class="pill" style="background:${css("--c" + (i % 8))}">Jaringan #${c.id + 1}</span><b>${c.size} akun</b><span class="mut">kerapatan ${c.density} · ${c.co_posts} posting berdekatan</span>
      ${c.narratives.map(n => `<a class="chip acc" href="#/case/${S.caseId}/narasi" onclick="S.narr='${n}'">${n}</a>`).join("")}</div>
      <div class="small">${c.members.map(m => `<span class="chip">${esc(m)}</span>`).join("")}</div></div>`).join("") || `<div class="mut small">Tidak ada kelompok ≥ 3 akun.</div>`}</div>
    <div class="card"><h2>Pola koordinasi</h2><div class="small mut">≥ ${r.params.coord_min_accounts} akun berbeda memposting narasi yang sama dalam ${r.params.coord_window_min} menit.</div>
      ${r.coordination.map(coordHtml).join("") || `<div class="mut small" style="margin-top:8px">Tidak ditemukan.</div>`}</div>
  </div>`;
  if (!net.nodes.length) return;
  const vn = new vis.DataSet(net.nodes.map(n => ({ id: n.id, label: n.id, size: 8 + n.degree * 2, color: n.community >= 0 ? css("--c" + (n.community % 8)) : css("--c7"), font: { color: css("--fg"), size: 11 } })));
  const ve = new vis.DataSet(net.edges.map((e, i) => ({ id: i, from: e.from, to: e.to, width: Math.min(6, e.weight), color: { color: css("--mut"), opacity: .4 }, title: `${e.weight} kali berdekatan` })));
  new vis.Network($("#accNet"), { nodes: vn, edges: ve }, { physics: { solver: "forceAtlas2Based", stabilization: { iterations: 200 } }, nodes: { shape: "dot" } });
}

/* ---------------------------------------------------------------- tab: hashtag */
function tabTags(el) {
  const H = S.result.hashtags;
  el.innerHTML = `<div class="card"><h2>Hashtag</h2><div class="small mut" style="margin-bottom:8px">Siapa yang pertama memakai tiap hashtag dan kapan puncaknya. Hashtag umum (#fyp, #viral) ditandai dan tidak dipakai untuk menautkan post.</div>
  <div class="tw"><table><tr><th>Hashtag</th><th class="num">Post</th><th class="num">Akun</th><th>Pertama dipakai</th><th>5 akun pertama</th><th>Puncak</th><th>Narasi</th><th>Sering bersama</th></tr>
  ${H.map(h => `<tr><td><b>#${esc(h.tag)}</b>${h.generic ? ` <span class="chip">umum</span>` : ""}</td><td class="num">${h.count}</td><td class="num">${h.authors}</td>
    <td>${pill(h.first.platform)} ${link(h.first.url, h.first.author)}<div class="small mut">${fmt(h.first.time)}</div></td>
    <td class="small">${h.first_authors.map(f => esc(f.author)).join(", ")}</td><td class="small">${fmt(h.peak_hour)} (${h.peak_count})</td>
    <td>${h.narratives.map(n => `<a class="chip acc" href="#/case/${S.caseId}/narasi" onclick="S.narr='${n}'">${n}</a>`).join("")}</td>
    <td class="small">${h.co_tags.map(t => "#" + esc(t)).join(" ")}</td></tr>`).join("") || `<tr><td colspan=8 class="mut">Tidak ada hashtag.</td></tr>`}</table></div></div>`;
}

/* ---------------------------------------------------------------- tab: akun */
function tabAccounts(el) {
  const A = S.result.accounts;
  el.innerHTML = `<div class="card"><div class="row spread"><h2 style="margin:0">Akun</h2><input type="text" id="aq" placeholder="Cari akun…" style="width:200px"></div>
  <div class="small mut" style="margin:6px 0 8px">Jangkauan = jumlah post yang diturunkan dari post asli akun ini. Pengaruh = PageRank di graf "siapa menyebarkan dari siapa".</div>
  <div class="tw" id="accT"></div></div>`;
  const draw = () => {
    const q = ($("#aq").value || "").toLowerCase();
    const rows = A.filter(a => !q || a.author.toLowerCase().includes(q)).slice(0, 200);
    $("#accT").innerHTML = `<table><tr><th>Akun</th><th>Platform</th><th class="num">Post</th><th>Post pertama</th><th class="num">Post asal</th><th class="num">Jangkauan</th><th class="num">Disebar ulang oleh</th><th class="num">Pengaruh</th><th>Narasi</th><th>Sikap</th><th>Catatan</th></tr>
    ${rows.map(a => `<tr><td><b>${esc(a.author)}</b></td><td>${a.platforms.map(pill).join(" ")}</td><td class="num">${a.posts}</td><td class="small">${fmt(a.first_post)}</td><td class="num">${a.origin_posts}</td><td class="num">${a.reach}</td><td class="num">${a.amplified_by}</td><td class="num">${a.influence}</td>
    <td>${a.narratives.map(n => `<a class="chip acc" href="#/case/${S.caseId}/narasi" onclick="S.narr='${n}'">${n}</a>`).join("")}</td><td>${stPill(a.stance)}</td><td>${a.flags.map(f => `<span class="flag">${esc(f)}</span>`).join("")}</td></tr>`).join("")}</table>`;
  };
  $("#aq").oninput = draw; draw();
}

/* ---------------------------------------------------------------- pengaturan */
async function openSettings() {
  const st = await api("/api/settings");
  const K = st.keys;
  const field = (k, label, hint) => `<label class="f"><span>${label}${K[k].from_env ? " (dari variabel lingkungan)" : ""}</span>
    <input type="password" data-k="${k}" placeholder="${K[k].set ? K[k].masked : "belum diisi"}" ${K[k].from_env ? "disabled" : ""} autocomplete="off"><span>${hint}</span></label>`;
  api("/api/camoufox/status").then(c => { const el = $("#cfInfo"); if (el) el.innerHTML = c.installed
    ? `<span class="chip">Camoufox terpasang</span>${c.profile ? `<span class="chip">profil login tersimpan</span>` : `<span class="chip">belum ada profil login</span>`}`
    : `<span class="chip warn">Camoufox belum terpasang</span> <span class="mut">jalankan <code>pip install camoufox</code> lalu <code>python -m camoufox fetch</code></span>`; });
  modal(`<h2>Pengaturan & token</h2>
    <div class="small mut" style="margin-bottom:12px">Token disimpan di <code>data/settings.json</code> di komputer ini saja. Kosongkan kolom untuk tidak mengubah; ketik <code>-</code> untuk menghapus.</div>
    <div class="grid" style="gap:12px">
      ${field("ANTHROPIC_API_KEY", "Anthropic API key", "Untuk ringkasan & penilaian narasi oleh Claude (opsional).")}
      ${field("X_BEARER_TOKEN", "X API bearer token", "Paket Basic: 7 hari terakhir. Paket Pro: arsip penuh.")}
      ${field("APIFY_TOKEN", "Apify token", "Alternatif untuk X & TikTok tanpa API resmi (berbayar per pemakaian).")}
      <div class="grid g2" style="gap:12px">${field("TIKTOK_CLIENT_KEY", "TikTok Research client key", "Khusus peneliti yang disetujui.")}${field("TIKTOK_CLIENT_SECRET", "TikTok Research client secret", "")}</div>
      <div class="grid g2" style="gap:12px">${field("BSKY_HANDLE", "Bluesky handle", "")}${field("BSKY_APP_PASSWORD", "Bluesky app password", "")}</div>
    </div>
    <div class="sep"></div>
    <h3>Camoufox (TikTok lewat browser)</h3>
    <div class="small" id="cfInfo" style="margin-bottom:8px"></div>
    ${field("CAMOUFOX_PROXY", "Proxy", "Format: http://user:pass@host:port atau socks5://host:port. Semua lalu lintas browser Camoufox lewat proxy ini, jadi TikTok tidak melihat IP Anda.")}
    <div class="row" style="margin-top:8px">
      <button class="btn sm" onclick="testProxy()">Tes proxy</button>
      <button class="btn sm" onclick="openLoginBrowser(this)">Buka browser untuk login / verifikasi</button>
    </div>
    <div class="small" id="proxyResult" style="margin-top:6px"></div>
    <div class="log" id="loginLog" style="margin-top:8px;display:none"></div>
    <div class="small mut" style="margin-top:6px">Login memakai akun TikTok Anda sendiri dan disimpan di profil lokal (<code>data/camoufox_profile</code>). Jendela browser hanya bisa muncul bila aplikasi dijalankan di komputer Anda, bukan di server tanpa layar. Sebaiknya pakai akun terpisah dari akun pribadi.</div>
    <div class="row" style="margin-top:16px;justify-content:flex-end"><button class="btn" onclick="closeModal()">Batal</button><button class="btn primary" onclick="saveSettings()">Simpan</button></div>`);
}
async function testProxy() {
  const inp = document.querySelector('.modal input[data-k="CAMOUFOX_PROXY"]');
  const el = $("#proxyResult"); el.innerHTML = `<span class="mut">Menguji…</span>`;
  try {
    const r = await api("/api/camoufox/test-proxy", { method: "POST", body: JSON.stringify({ proxy: inp.value && inp.value !== "-" ? inp.value : "" }) });
    el.innerHTML = r.hidden ? `<span class="chip">IP terlihat: ${esc(r.via_proxy)}</span> <span class="mut">IP asli Anda (${esc(r.direct)}) tersembunyi.</span>`
      : `<span class="chip warn">IP lewat proxy: ${esc(r.via_proxy)}</span> <span class="mut">${r.direct ? "sama dengan IP asli, proxy tidak menyembunyikan IP Anda" : "IP asli tidak bisa dicek"}</span>`;
  } catch (e) { el.innerHTML = `<span class="chip warn">${esc(e.message)}</span>`; }
}
async function openLoginBrowser(btn) {
  btn.disabled = true;
  const { job } = await api("/api/camoufox/login", { method: "POST" });
  const lg = $("#loginLog"); lg.style.display = "block";
  const tick = async () => { const j = await api(`/api/jobs/${job}`); if (!$("#loginLog")) return;
    $("#loginLog").textContent = j.log.trim(); if (j.status === "running") setTimeout(tick, 1500); else btn.disabled = false; };
  tick();
}
async function saveSettings() {
  const body = {};
  document.querySelectorAll(".modal input[data-k]").forEach(i => { if (i.value === "-") body[i.dataset.k] = ""; else if (i.value) body[i.dataset.k] = i.value; });
  try { await api("/api/settings", { method: "POST", body: JSON.stringify(body) }); }
  catch (e) { return toast(e.message); }
  closeModal(); toast("Pengaturan disimpan"); if (S.tab === "data" && S.caseId) render();
}

/* ---------------------------------------------------------------- modal */
function modal(html) { closeModal(); const bg = document.createElement("div"); bg.className = "modal-bg"; bg.id = "modal"; bg.innerHTML = `<div class="modal">${html}</div>`; bg.onclick = e => { if (e.target === bg) closeModal(); }; document.body.appendChild(bg); }
function closeModal() { $("#modal")?.remove(); }
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

route();
