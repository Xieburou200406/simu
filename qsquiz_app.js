/* qsquiz 前端逻辑：macOS 风格 SPA（原生 JS，无构建链） */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const GLYPHS = {
  "all": ["全", "g-blue"], "options-basic": ["Δ", "g-indigo"],
  "sse": ["上", "g-teal"], "szse": ["深", "g-green"],
  "cffex": ["金", "g-orange"], "comdty": ["商", "g-brown"],
  "broker-counter": ["柜", "g-indigo"], "qs": ["Q", "g-graphite"],
  "option-strategies": ["策", "g-pink"], "futures-basics": ["期", "g-graphite"],
};

const S = {
  meta: null, modules: [],
  mode: "practice",            // practice | test | exam
  module: "all",               // 选中的练习模块
  view: "start",               // start | paper | summary | results | login
  session: null,               // 当前答题会话
  idx: 0,                      // 练习游标
  skew: 0,                     // 服务器时钟偏差（秒）
  timerId: null,
  submitting: false,
};

/* ---------------- 工具 ---------------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtClock(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}

function fmtTime(epoch) {
  const d = new Date(epoch * 1000);
  const p = n => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  } : {});
  let data = {};
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) {
    const err = new Error(data.error || `请求失败 (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(title, body = "", type = "info") {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<span class="dot ${type === "err" ? "err" : "info"}">${type === "err" ? "!" : "i"}</span>
    <div><div class="t-title">${esc(title)}</div>${body ? `<div class="t-body">${esc(body)}</div>` : ""}</div>`;
  $("#toastLayer").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, 3800);
}

function modName(id) {
  if (id === "all") return "全部模块";
  const m = S.modules.find(x => x.id === id);
  return m ? m.name : id;
}

/* ---------------- 初始化 ---------------- */

async function init() {
  try {
    S.meta = await api("/api/meta");
    S.modules = S.meta.modules.filter(m => m.enabled);
  } catch (e) {
    toast("服务不可用", String(e.message), "err");
    return;
  }
  bindChrome();
  renderSidebar();
  renderToolbar();

  // 恢复进行中的考试
  const sid = localStorage.getItem("qsquiz.exam");
  if (sid) {
    try {
      const s = await api("/api/session/" + sid);
      if (s.mode === "exam" && !s.submitted_at) {
        S.skew = Date.now() / 1000 - s.server_now;
        S.session = s;
        S.mode = "exam";
        S.view = "paper";
        startTimer();
        render();
        return;
      }
      localStorage.removeItem("qsquiz.exam");
    } catch (e) {
      localStorage.removeItem("qsquiz.exam");
    }
  }
  route();
}

function bindChrome() {
  $("#seg").addEventListener("click", e => {
    const btn = e.target.closest("button[data-mode]");
    if (!btn) return;
    setMode(btn.dataset.mode);
  });
  $("#btnZoom").addEventListener("click", () => $("#win").classList.toggle("zoomed"));
  $("#navToggle").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $("#navExam").addEventListener("click", () => { setMode("exam"); closeSidebar(); });
  $("#navResults").addEventListener("click", () => { showResults(); closeSidebar(); });
  $("#moduleList").addEventListener("click", e => {
    const item = e.target.closest("[data-module]");
    if (!item) return;
    S.module = item.dataset.module;
    renderSidebar();
    if (S.mode === "exam") setMode("practice");
    else route();
    closeSidebar();
  });
}

function closeSidebar() { $("#sidebar").classList.remove("open"); }

function setMode(mode) {
  if (S.mode === mode && S.view !== "results") { route(); return; }
  S.mode = mode;
  stopTimer();
  S.session = null;
  S.idx = 0;
  route();
}

function route() {
  S.view = S.mode === "exam" ? "login" : "start";
  render();
}

/* ---------------- 侧边栏 / 工具栏 ---------------- */

function renderSidebar() {
  const items = [{ id: "all", name: "全部模块", count_test: S.modules.reduce((a, m) => a + m.count_test, 0) }]
    .concat(S.modules.map(m => ({ ...m })));
  $("#moduleList").innerHTML = items.map(m => {
    const [g, cls] = GLYPHS[m.id] || ["题", "g-blue"];
    return `<button class="side-item ${S.module === m.id && S.mode !== "exam" ? "on" : ""}" data-module="${esc(m.id)}">
      <i class="glyph ${cls}">${g}</i><span>${esc(m.name)}</span>
      <span class="count">${m.count_test}</span></button>`;
  }).join("");
  $("#navExam").classList.toggle("on", S.mode === "exam" && S.view !== "results");
  $("#navResults").classList.toggle("on", S.view === "results");
}

function renderToolbar() {
  $$("#seg button").forEach(b => b.classList.toggle("on", b.dataset.mode === S.mode));
  const idx = ["practice", "test", "exam"].indexOf(S.mode);
  $("#segThumb").style.transform = `translateX(${idx * 64}px)`;

  const prog = $("#tbProgress");
  if (S.view === "paper" && S.session) {
    const t = S.session.total || (S.session.paper || []).length;
    let cur, txt;
    if (S.session.mode === "practice") {
      cur = S.idx + 1; txt = `第 ${Math.min(cur, t)} / ${t} 题`;
    } else {
      const done = Object.keys(S.session.answers || {}).length;
      cur = done; txt = `已答 ${done} / ${t}`;
    }
    prog.classList.remove("hidden");
    $("#progText").textContent = txt;
    $("#progFill").style.width = (t ? (cur / t) * 100 : 0) + "%";
  } else {
    prog.classList.add("hidden");
  }
  $("#timer").classList.toggle("hidden", !(S.view === "paper" && S.session && S.session.mode === "exam"));
}

function setTitle(t) { $("#winTitle").textContent = t; }

/* ---------------- 视图渲染 ---------------- */

function render() {
  stopRenderTimerOnly();
  renderToolbar();
  const c = $("#content");
  c.scrollTop = 0;
  if (S.view === "start") renderStart(c);
  else if (S.view === "login") renderLogin(c);
  else if (S.view === "paper") renderPaper(c);
  else if (S.view === "summary") renderSummary(c);
  else if (S.view === "results") renderResultsTable(c);
}

let renderTimerHandle = null;
function stopRenderTimerOnly() {
  if (renderTimerHandle) { clearInterval(renderTimerHandle); renderTimerHandle = null; }
}

/* ----- 开始面板 ----- */

function renderStart(c) {
  const isTest = S.mode === "test";
  const [g, cls] = GLYPHS[S.module] || ["题", "g-blue"];
  const mod = S.modules.find(m => m.id === S.module);
  const n = isTest ? S.meta.paper : (mod ? mod.count_test : S.meta.modules.reduce((a, m) => a + (m.enabled ? m.count_test : 0), 0));
  setTitle(isTest ? "测试" : "练习 · " + modName(S.module));
  c.innerHTML = `
    <div class="hero">
      <div class="glyph-lg ${isTest ? "" : cls}"
           style="${isTest ? "background:linear-gradient(180deg,#4fd167,#30b94c)" : ""}">${isTest ? "测" : g}</div>
      <h1>${isTest ? "模块测试" : esc(modName(S.module)) + " · 练习"}</h1>
      <p>${isTest
        ? `全部启用模块混抽 <b>${S.meta.paper}</b> 题，交卷后出分并回顾错题。<br>与考试题库完全隔离，随时可测。`
        : `本模块已入库 <b>${n}</b> 题，逐题作答即时反馈。<br>选项顺序每次打乱，请记住答案本身而不是字母。`}</p>
      <div class="meta-chips">
        <span class="chip">题库：test 库</span>
        <span class="chip">${isTest ? "固定 " + S.meta.paper + " 题" : "每次 " + Math.min(20, n) + " 题"}</span>
        <span class="chip">${isTest ? "交卷出分" : "即时解析"}</span>
        <span class="chip">不计时</span>
      </div>
      <button class="btn" id="btnStart">${isTest ? "开始测试" : "开始练习"}</button>
    </div>`;
  $("#btnStart").addEventListener("click", startPracticeOrTest);
}

async function startPracticeOrTest() {
  try {
    const data = await api("/api/start", { mode: S.mode, module: S.mode === "practice" ? S.module : "all" });
    S.skew = Date.now() / 1000 - data.server_now;
    S.session = { ...data, answers: {}, feedback: {} };
    S.idx = 0;
    S.view = "paper";
    render();
  } catch (e) {
    toast("无法开始", e.message, "err");
  }
}

/* ----- 考试登录 ----- */

function renderLogin(c) {
  setTitle("考试登录");
  c.innerHTML = `
    <form class="form-card" id="examForm">
      <h2>考试</h2>
      <p class="sub">凭 token 进入；计时以服务器为准，中途关闭页面可重进续答。</p>
      <div class="field">
        <label for="fToken">考试 Token</label>
        <input id="fToken" class="token-mono" placeholder="XXXX-XXXX" autocomplete="off" required>
      </div>
      <div class="field">
        <label for="fName">姓名</label>
        <input id="fName" placeholder="将记录在成绩单中" autocomplete="off" required>
      </div>
      <div class="actions">
        <button type="submit" class="btn">进入考试</button>
      </div>
    </form>`;
  $("#examForm").addEventListener("submit", async e => {
    e.preventDefault();
    const token = $("#fToken").value.trim(), name = $("#fName").value.trim();
    if (!token || !name) return;
    try {
      const data = await api("/api/exam/login", { token, name });
      S.skew = Date.now() / 1000 - data.server_now;
      S.session = { ...data, mode: "exam", answers: {}, feedback: {} };
      localStorage.setItem("qsquiz.exam", data.sid);
      S.view = "paper";
      startTimer();
      render();
    } catch (err) {
      toast("无法进入考试", err.message, "err");
    }
  });
}

/* ----- 答题 ----- */

function renderPaper(c) {
  const s = S.session;
  if (s.mode === "practice") { renderPracticeQ(c); return; }
  setTitle(s.mode === "exam" ? "考试 · " + (s.name || "") : "测试");
  const total = s.total || s.paper.length;   // resume 路径无 total，取 paper 长度
  const answered = Object.keys(s.answers || {}).length;
  c.innerHTML = `
    <div class="paper-wrap">
      ${s.paper.map((q, i) => questionCard(q, i, s)).join("")}
    </div>
    <div class="submit-bar">
      <span class="info">共 ${total} 题 · 已答 ${answered} · 未答 ${total - answered}</span>
      ${s.mode === "exam" ? '<span class="info">到点自动交卷</span>' : ""}
      <button class="btn" id="btnSubmit">交卷</button>
    </div>`;
  c.querySelectorAll(".opt input").forEach(inp => {
    inp.addEventListener("change", async () => {
      const card = inp.closest(".q-card");
      const qid = card.dataset.qid;
      const q = s.paper.find(x => x.id === qid);
      const choice = q.options[+inp.dataset.i];
      s.answers[qid] = choice;
      renderToolbar();
      try { await api("/api/answer", { sid: s.sid, qid, choice }); }
      catch (e) { if (e.status === 403) { toast("考试已结束", "正在自动交卷…", "err"); submitPaper(true); } }
    });
  });
  $("#btnSubmit").addEventListener("click", () => confirmSubmit(s.total - answered));
  // 交卷条固定在内容区底部：content 需要 relative
  c.style.position = "relative";
}

function questionCard(q, i, s) {
  const sel = (s.answers || {})[q.id];
  return `
    <div class="q-card" data-qid="${esc(q.id)}" style="--i:${i}">
      <div class="q-head"><span class="q-no">${String(i + 1).padStart(2, "0")}</span>
        <span class="q-tag">${esc(modName(q.module))}</span></div>
      <p class="q-text">${esc(q.q)}</p>
      <div class="opts">
        ${q.options.map((o, j) => `
          <label class="opt">
            <input type="radio" name="${esc(q.id)}" data-i="${j}" ${sel === o ? "checked" : ""}>
            <span class="letter">${"ABCD"[j]}</span>
            <span class="otext">${esc(o)}</span>
          </label>`).join("")}
      </div>
    </div>`;
}

/* 练习：单题逐答 */

function renderPracticeQ(c) {
  const s = S.session;
  const q = s.paper[S.idx];
  setTitle("练习 · " + modName(S.module));
  const fb = (s.feedback || {})[q.id];
  c.innerHTML = `
    <div class="paper-wrap" style="margin-top:2vh">
      <div class="q-card" data-qid="${esc(q.id)}" style="--i:0">
        <div class="q-head"><span class="q-no">${String(S.idx + 1).padStart(2, "0")}</span>
          <span class="q-tag">${esc(modName(q.module))}</span></div>
        <p class="q-text">${esc(q.q)}</p>
        <div class="opts" id="pOpts">
          ${q.options.map((o, j) => `
            <label class="opt ${fb ? (o === fb.answer ? "correct" : ((s.answers[q.id] === o) ? "wrong" : "dim")) : ""} ${fb ? "locked" : ""}">
              <input type="radio" name="${esc(q.id)}" data-i="${j}" ${s.answers[q.id] === o ? "checked" : ""} ${fb ? "disabled" : ""}>
              <span class="letter">${"ABCD"[j]}</span>
              <span class="otext">${esc(o)}</span>
              <span class="mark">${fb ? (o === fb.answer ? "✓" : ((s.answers[q.id] === o) ? "✕" : "")) : ""}</span>
            </label>`).join("")}
        </div>
        ${fb ? `<div class="explain"><b>${fb.correct ? "回答正确" : "回答错误"}</b> · 正确答案：${esc(fb.answer)}<br>${esc(fb.explain)}</div>` : ""}
      </div>
      <div class="q-nav">
        <span class="chip">${S.idx + 1} / ${s.total}</span>
        ${fb ? `<button class="btn" id="btnNext">${S.idx + 1 >= s.total ? "查看小结" : "下一题"}</button>` : `<span class="chip">作答后显示解析</span>`}
      </div>
    </div>`;
  $$("#pOpts input").forEach(inp => {
    inp.addEventListener("change", async () => {
      const q2 = s.paper[S.idx];
      const choice = q2.options[+inp.dataset.i];
      s.answers[q2.id] = choice;
      try {
        const fb = await api("/api/answer", { sid: s.sid, qid: q2.id, choice });
        s.feedback = s.feedback || {};
        s.feedback[q2.id] = fb;
        renderPracticeQ(c);       // 重渲染出反馈态
        renderToolbar();
      } catch (e) { toast("提交失败", e.message, "err"); }
    });
  });
  const next = $("#btnNext");
  if (next) next.addEventListener("click", () => {
    if (S.idx + 1 >= s.total) { S.view = "summary"; render(); }
    else { S.idx++; renderPracticeQ(c); renderToolbar(); }
  });
}

function renderSummary(c) {
  const s = S.session;
  const fbs = s.feedback || {};
  const answered = Object.keys(fbs).length;
  const right = Object.values(fbs).filter(f => f.correct).length;
  setTitle("练习小结");
  c.innerHTML = `
    <div class="hero">
      <div class="glyph-lg" style="background:linear-gradient(180deg,#4aa3ff,#1878f0)">练</div>
      <h1>练习小结</h1>
      <p>作答 ${answered} / ${s.total} 题 · 正确 <b>${right}</b> 题 · 正确率 <b>${answered ? Math.round(right / answered * 100) : 0}%</b></p>
      <div class="meta-chips"><span class="chip">${esc(modName(s.module === "all" ? "all" : s.module))}</span></div>
      <div style="display:flex;gap:10px;justify-content:center">
        <button class="btn" id="btnAgain">再练一组</button>
        <button class="btn sec" id="btnHome">返回</button>
      </div>
    </div>`;
  $("#btnAgain").addEventListener("click", startPracticeOrTest);
  $("#btnHome").addEventListener("click", route);
}

/* ----- 计时（考试） ----- */

function startTimer() {
  stopTimer();
  S.timerId = setInterval(tick, 250);
  tick();
}

function stopTimer() {
  if (S.timerId) { clearInterval(S.timerId); S.timerId = null; }
}

function tick() {
  const s = S.session;
  if (!s || s.mode !== "exam" || !s.deadline) return;
  const now = Date.now() / 1000 - S.skew;
  const remain = s.deadline - now;
  const el = $("#timer");
  el.textContent = fmtClock(remain);
  el.classList.toggle("warn", remain <= 60);
  if (remain <= 0 && !S.submitting) {
    toast("时间到", "正在自动交卷");
    submitPaper(true);
  }
}

/* ----- 交卷 ----- */

function confirmSubmit(unanswered) {
  const layer = $("#sheetLayer");
  layer.classList.remove("hidden");
  layer.innerHTML = `
    <div class="sheet" style="width:min(420px,100%)">
      <h2>确认交卷？</h2>
      <p class="sub">${unanswered > 0 ? `还有 ${unanswered} 题未作答，未答题按错误计。` : "全部题目已作答。"}</p>
      <div class="actions">
        <button class="btn sec" id="scCancel">继续作答</button>
        <button class="btn" id="scOk">交卷</button>
      </div>
    </div>`;
  $("#scCancel").addEventListener("click", closeSheet);
  $("#scOk").addEventListener("click", () => submitPaper(false));
}

function closeSheet() {
  $("#sheetLayer").classList.add("hidden");
  $("#sheetLayer").innerHTML = "";
}

async function submitPaper(auto) {
  const s = S.session;
  if (!s || S.submitting) return;
  S.submitting = true;
  try {
    const r = await api("/api/submit", { sid: s.sid });
    stopTimer();
    localStorage.removeItem("qsquiz.exam");
    showResultSheet(r, auto);
  } catch (e) {
    toast("交卷失败", e.message, "err");
  } finally {
    S.submitting = false;
  }
}

function showResultSheet(r, auto) {
  const s = S.session;
  const pct = r.total ? Math.round(r.score / r.total * 100) : 0;
  const wrongs = r.items.filter(it => !it.ok);
  const usedSec = s.started_at ? (Date.now() / 1000 - S.skew - s.started_at) : 0;
  const layer = $("#sheetLayer");
  layer.classList.remove("hidden");
  layer.innerHTML = `
    <div class="sheet">
      <h2>${s.mode === "exam" ? "考试成绩" : "测试成绩"}${auto ? "（已到时自动交卷）" : ""}</h2>
      <p class="sub">${s.mode === "exam" ? `姓名：${esc(s.name || "-")} · 成绩已记录` : "成绩不记录，可反复测试"}</p>
      <div class="score-hero">
        <div class="score-ring" style="--pct:${pct}">
          <div><span class="n">${r.score}</span><span class="d">/ ${r.total}</span></div>
        </div>
        <div class="lines">
          <div class="line">得分率 <b>${pct}%</b></div>
          <div class="line">答对 <b>${r.score}</b> 题 · 答错/未答 <b>${r.total - r.score}</b> 题</div>
          <div class="line">用时约 <b>${fmtClock(Math.min(usedSec, 24 * 3600))}</b></div>
        </div>
      </div>
      ${wrongs.length ? `
        <div class="wrong-list">
          ${wrongs.map((it, i) => `
            <div class="wrong-item" style="--i:${i}">
              <div class="wq">${esc(it.q)}</div>
              <div class="wa"><span class="bad-t">你的答案：${it.your ? esc(it.your) : "未答"}</span>
                · <span class="ok-t">正确：${esc(it.answer)}</span>
                ${it.explain ? `<br>${esc(it.explain)}` : ""}</div>
            </div>`).join("")}
        </div>` : `<p class="empty" style="padding:14px 0">全对，漂亮。</p>`}
      <div class="actions">
        ${s.mode === "test" ? '<button class="btn sec" id="rsAgain">再来一组</button>' : ""}
        <button class="btn" id="rsClose">完成</button>
      </div>
    </div>`;
  $("#rsClose").addEventListener("click", () => { closeSheet(); route(); });
  const again = $("#rsAgain");
  if (again) again.addEventListener("click", () => { closeSheet(); startPracticeOrTest(); });
}

/* ----- 成绩单 ----- */

async function showResults() {
  S.view = "results";
  renderSidebar();
  renderToolbar();
  const c = $("#content");
  try {
    const data = await api("/api/results");
    renderResultsTable(c, data.results);
  } catch (e) {
    toast("无法加载成绩", e.message, "err");
  }
}

function renderResultsTable(c, rows) {
  setTitle("考试成绩单");
  renderSidebar();
  rows = rows || [];
  c.innerHTML = `
    <div class="results-wrap">
      <h1>考试成绩单</h1>
      ${rows.length ? `
        <table class="rt">
          <thead><tr><th>时间</th><th>姓名</th><th>成绩</th><th>得分率</th><th>用时</th></tr></thead>
          <tbody>
            ${rows.map(r => {
              const pct = r.total ? Math.round(r.score / r.total * 100) : 0;
              const cls = pct >= 85 ? "good" : pct >= 60 ? "mid" : "bad";
              return `<tr>
                <td class="num">${fmtTime(r.submitted_at)}</td>
                <td>${esc(r.name || "-")}</td>
                <td class="num">${r.score} / ${r.total}</td>
                <td class="num ${cls}">${pct}%</td>
                <td class="num">${fmtClock(r.submitted_at - r.started_at)}</td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>` : `<div class="empty">还没有考试记录</div>`}
    </div>`;
}

init();
