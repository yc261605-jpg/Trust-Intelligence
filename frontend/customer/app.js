// 車主端：掃專屬 QR → 確認車牌 → 等待（檢查進度＋愛車紀錄）→ 決策卡 → 證據頁 → 施工進度 → 交車摘要＋回廠提醒
const hero = document.getElementById("hero");
const app = document.getElementById("app");
const dock = document.getElementById("dock");
const qrToken = new URLSearchParams(location.search).get("t") || sessionStorage.getItem("custFor") || "";

const state = { order: null, choices: {}, preset: null, sig: "", detail: null, chatOpen: false, chatCount: -1, handoff: null };
const shortName = (n) => n.replace(/（.*?）/, "");
const DEFAULT_PHOTO = "/static/img/hero_service_bay.jpg";
const sum = (arr) => arr.reduce((s, i) => s + i.price, 0);

// ---------- 共用：照片主視覺＋玻璃頂部列 ----------
function setHero({ photo, left, right = "", eyebrow = "", title = "", meta = "", short = false, journey = "" }) {
  const src = photo || DEFAULT_PHOTO;
  const still = hero.dataset.src === src;          // 同一張照片＝同一頁的更新，不重播進場動畫
  hero.dataset.src = src;
  hero.className = "hero" + (short ? " short" : "") + (journey ? "" : " nj") + (still ? " still" : "");
  document.body.style.setProperty("--bg-photo", `url('${src}')`);
  hero.innerHTML = `<div class="photo" style="background-image:url('${esc(src)}')"></div><div class="shade"></div>
    <div class="bar glass-dark">${left}${right}</div>
    ${title ? `<div class="title">${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ""}<h1>${title}</h1>${meta ? `<div class="meta">${meta}</div>` : ""}</div>` : ""}
    ${journey}`;
}
const JOURNEY = ["檢查", "確認", "施工", "交車"];
const JOURNEY_AT = { created: 0, inspecting: 0, awaiting_customer: 1, confirmed: 2, in_progress: 2, completed: 3 };
function journeyHtml(status) {
  const at = JOURNEY_AT[status];
  return `<div class="journey glass-dark">${JOURNEY.map((j, i) =>
    `<span class="${i < at || status === "completed" ? "done" : i === at ? "now" : ""}">${j}</span>`).join("")}</div>`;
}
// 換頁時才播進場動畫（輪詢更新不重播）
let lastView = "";
function enter(view, cls = "anim") {
  if (view === lastView) return;
  lastView = view;
  stagger(app, cls);
}
const BRAND = () => brandHtml();
function setDock(html, col = false) {
  if (!html) { dock.className = ""; dock.innerHTML = ""; return; }
  const inner = dock.querySelector(".inner");
  if (inner) { inner.innerHTML = html; inner.classList.toggle("col", col); return; }   // 已在畫面上就只換內容，不再彈一次
  dock.className = "dock";
  dock.innerHTML = `<div class="inner glass ${col ? "col" : ""}">${html}</div>`;
}

// ---------- 登入：確認車牌 ----------
async function renderLogin(msg = "") {
  setDock("");
  if (!qrToken) {
    setHero({ left: BRAND(), title: "請掃描服務人員給你的 QR Code", eyebrow: "歡迎回廠" });
    app.innerHTML = `<div class="card login-card"><p class="lead">掃描後確認車牌，就能即時看到愛車的檢查結果。</p></div>${FOOTER}`;
    return;
  }
  let pv;
  try {
    pv = await api("GET", `/api/customer/preview?token=${encodeURIComponent(qrToken)}`);
  } catch (err) {
    setHero({ left: BRAND(), title: "QR Code 已失效", eyebrow: "請洽服務人員" });
    app.innerHTML = `<div class="card login-card"><p class="lead">${esc(err.message)}</p></div>${FOOTER}`;
    return;
  }
  setHero({ photo: pv.image_url, left: BRAND(), eyebrow: `${esc(pv.owner_name)}，歡迎回廠`, title: esc(pv.model) });
  app.innerHTML = `
    <div class="card login-card">
      <div class="faint">你的車牌</div>
      <div class="hint">${esc(pv.plate_hint)}</div>
      <form id="loginForm" class="mt">
        <p class="muted small" style="margin:0 0 10px">為了保護你的資料，請輸入完整車牌，確認是你的車</p>
        <input class="input big" name="plate" placeholder="例如 ABC-1234" autocomplete="off" autocapitalize="characters" required>
        ${msg ? `<p class="small" style="color:var(--red);margin:8px 0 0">${esc(msg)}</p>` : ""}
        <button class="btn primary block lg mt" type="submit">確認，查看我的車</button>
      </form>
    </div>${FOOTER}`;
  enter("login");
  document.getElementById("loginForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("POST", "/api/customer/login", { token: qrToken, plate: e.target.plate.value });
      sessionStorage.setItem("custToken", r.access_token);
      sessionStorage.setItem("custFor", qrToken);
      history.replaceState(null, "", location.pathname);
      start();
    } catch (err) { renderLogin(err.message); }
  };
}

// ---------- 讀取與重畫 ----------
async function load() {
  try {
    return await api("GET", "/api/customer/work-order", undefined, { customer: true });
  } catch (err) {
    if (err.status === 401) { sessionStorage.removeItem("custToken"); renderLogin(err.message); return null; }
    throw err;
  }
}

function signature(o) {
  const p = o.progress;
  const work = (o.items || []).map((i) => i.work_status).join(",");
  return `${o.status}|${p.checked}|${p.km_done}|${o.events.length}|${work}|${o.eta}`;
}

async function refresh(force = false) {
  const o = await load();
  if (!o) return;
  const sig = signature(o);
  if (!force && sig === state.sig) return;
  // 決策卡：狀態沒變就不重畫，避免洗掉車主正在做的選擇
  if (!force && state.order?.status === "awaiting_customer" && o.status === "awaiting_customer") return;
  const statusChanged = state.order && state.order.status !== o.status;
  state.order = o;
  state.sig = sig;
  if (statusChanged) state.detail = null;
  render();
  if (statusChanged) {
    window.scrollTo(0, 0);
    if (o.status === "awaiting_customer") { toast("檢查完成！你的決策卡已經出來了", "ok"); navigator.vibrate?.(200); }
  }
}

function showError(err) {
  setHero({ left: BRAND(), title: "暫時連不上" });
  app.innerHTML = `<div class="card login-card"><p class="lead">${esc(err.message)}</p>
    <button class="btn primary mt" onclick="start()">再試一次</button></div>${FOOTER}`;
}

const STATUS_LINE = {
  created: [true, "即將開始檢查"],
  inspecting: [true, "技師檢查中"],
  awaiting_customer: [false, "等你確認"],
  confirmed: [true, "準備施工"],
  in_progress: [true, "施工中"],
  completed: [false, "可以交車了"],
};

function mainHero(o, photo, title) {
  const v = o.vehicle;
  const [live, txt] = STATUS_LINE[o.status];
  setHero({
    photo: photo || v.image_url, left: BRAND(),
    right: `<span class="st">${live ? `<span class="pulse"></span>` : ""}${txt}</span>`,
    eyebrow: `${esc(v.owner_name)}的愛車`, title: title || esc(v.model),
    meta: `<span class="plate-w">${esc(v.plate)}</span>${o.current_km ? `<span>${o.current_km.toLocaleString()} km</span>` : ""}`,
    journey: journeyHtml(o.status),
  });
}

function render() {
  const o = state.order;
  if (o.status === "awaiting_customer" && state.detail) return renderDetail();
  if (o.status === "created" || o.status === "inspecting") renderWaiting(o);
  else if (o.status === "awaiting_customer") renderDecision(o);
  else if (o.status === "completed") renderSummary(o);
  else renderProgress(o);
}

const askDock = (qs) => setDock(`<div class="qchips">${qs.map((q) =>
  `<button class="btn" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
  <button class="btn primary" onclick="openChat()">問 AI</button>`, false);
function bindAskDock(item = null) {
  dock.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => openChat(item, b.dataset.q)));
}

// ---------- 等待：檢查進度＋愛車紀錄 ----------
function renderWaiting(o) {
  mainHero(o);
  const w = o.waiting;
  const p = o.progress;
  const total = p.total + (p.auto_total ? 1 : 0);
  const done = o.status === "created" ? 0 : p.checked + (p.km_done ? 1 : 0);
  const pct = Math.round((done / Math.max(1, total)) * 100);
  const mins = w.started_at ? Math.max(5, w.inspect_minutes - Math.round((Date.now() - Date.parse(w.started_at)) / 60000)) : w.inspect_minutes;
  const autos = w.checklist.filter((c) => c.auto);
  const techs = w.checklist.filter((c) => !c.auto);
  const firstOpen = o.status === "inspecting" ? techs.findIndex((c) => !c.checked) : -1;
  const dot = (on, now) => `<span class="dot ${on ? "ok" : now ? "now" : ""}">${on ? "✓" : ""}</span>`;
  app.innerHTML = `
    <div class="card">
      <div class="row between"><h2 style="margin:0">檢查進度</h2><span class="faint">${o.status === "created" ? "等待技師開始" : `約再 ${mins} 分鐘`}</span></div>
      <div class="pbar"><span style="width:${pct}%"></span></div>
      <div class="row between small mt-s"><b>已完成 ${done}/${total}</b><span class="faint">完成後決策卡會自動出現</span></div>
    </div>
    <div class="card">
      <h2>這次檢查的項目</h2>
      ${autos.length ? `<div class="ck ${p.km_done ? "" : "off"}">${dot(p.km_done, false)}
        <div class="grow"><b>里程項目 ${autos.length} 項</b><div class="faint">${esc(autos.map((c) => shortName(c.name)).join("、"))}</div></div>
        <span class="faint small">系統自動計算</span></div>` : ""}
      ${techs.map((c, i) => `<div class="ck ${c.checked || i === firstOpen ? "" : "off"}">${dot(c.checked, i === firstOpen)}
        <img src="${esc(c.image_url)}" alt=""><span class="grow">${esc(shortName(c.name))}</span>
        <span class="faint small">${c.checked ? "已檢查" : i === firstOpen ? "檢查中" : "技師量測拍照"}</span></div>`).join("")}
    </div>
    <div class="card"><h2>愛車保養紀錄</h2>
      ${w.visits.length ? w.visits.map((v) => `<div class="visit"><div><div class="d">${v.date.replaceAll("-", "/")}</div>
        <div class="faint">${v.km.toLocaleString()} km</div></div><div class="small muted">${esc(v.parts.join("、"))}</div></div>`).join("")
        : `<p class="muted small" style="margin:0">這是第一次回廠保養，交車日 ${esc(o.vehicle.delivered_on.replaceAll("-", "/"))}。</p>`}
    </div>${FOOTER}`;
  askDock(["會檢查哪些項目？", "還要多久？", "上次換了什麼？"]);
  bindAskDock();
  enter("waiting");
}

// ---------- 決策卡 ----------
function choiceSeg(it) {
  if (it.level === "immediate") return `<div class="locked">今天必須處理・低於安全門檻</div>`;
  if (it.level !== "deferrable") return "";
  const c = state.choices[it.id];
  return `<div class="seg"><button class="${c === "today" ? "on" : ""}" data-item="${it.id}" data-c="today">今天換</button>
    <button class="${c === "defer" ? "on" : ""}" data-item="${it.id}" data-c="defer">延後，到時提醒我</button></div>`;
}

function itemCard(it) {
  return `<div class="icard" id="item-${it.id}">
    <div class="top" data-open="${it.id}"><img class="th" src="${esc(it.photos[0] || it.image_url)}" alt="">
      <div class="grow"><div class="row between"><span class="nm">${esc(shortName(it.name))}</span><span class="price">${money(it.price)}</span></div>
        <div class="bs">${esc(it.basis || "")}</div>
        <button class="ev" data-open="${it.id}">看證據${it.photos.length ? `・照片 ${it.photos.length}` : ""} ›</button></div></div>
    ${choiceSeg(it)}</div>`;
}

function renderDecision(o) {
  mainHero(o, null, "檢查完成，請你確認");
  const by = (lv) => o.items.filter((i) => i.level === lv);
  const imm = by("immediate"), def = by("deferrable"), ok = by("normal");
  for (const it of imm) state.choices[it.id] = "today";
  let vi = 0;
  const vrow = (lv, list, t, sub, price) => `<div class="vrow"><span class="chip ${lv} drop-in" style="--i:${vi++}">${list.length}</span>
    <div class="grow"><div class="t">${t}</div><div class="faint">${sub}</div></div><span class="price">${price}</span></div>`;
  app.innerHTML = `
    <div class="card">
      ${imm.length ? vrow("immediate", imm, "今天必須處理", esc(imm.map((i) => shortName(i.name)).join("、")), money(sum(imm))) : ""}
      ${def.length ? vrow("deferrable", def, "由你決定", esc(def.map((i) => shortName(i.name)).join("、")), money(sum(def))) : ""}
      ${vrow("normal", ok, "今天不用換", "狀況良好，照片與紀錄都保留", "NT$0")}
      <p class="faint small" style="margin:8px 0 0">依技師量測與原廠規則 ${esc(o.rule_version)} 分級</p>
    </div>
    ${def.length ? `<div class="card"><h2 style="margin:0">一鍵選擇</h2>
      <div class="seg preset-seg">
        <button class="${state.preset === "must" ? "on" : ""}" data-preset="must"><b>只換必要的</b><span>${money(sum(imm))}</span></button>
        <button class="${state.preset === "all" ? "on" : ""}" data-preset="all"><b>建議的都換</b><span>${money(sum(imm) + sum(def))}</span></button></div>
      <p class="faint small" style="margin:8px 0 0">也可以在下方逐項調整</p></div>` : ""}
    ${imm.length ? `<div class="sec"><span class="lvdot immediate"></span>今天必須處理<span class="faint">${imm.length} 項</span></div>${imm.map(itemCard).join("")}` : ""}
    ${def.length ? `<div class="sec"><span class="lvdot deferrable"></span>由你決定<span class="faint">${def.length} 項</span></div>${def.map(itemCard).join("")}` : ""}
    <details class="card okd"><summary><span class="chip normal">${ok.length}</span>
      <div class="grow"><div class="t" style="font-weight:800;font-size:16px">今天不用換</div><div class="faint">點開看每一項的量測與照片</div></div><span class="chev">›</span></summary>
      ${ok.map((i) => `<div class="nrow" data-open="${i.id}"><img src="${esc(i.photos[0] || i.image_url)}" alt="">
        <div class="grow"><div class="nm">${esc(shortName(i.name))}</div><div class="faint small">${esc(i.basis || "")}</div></div><span class="chev">›</span></div>`).join("")}
    </details>${FOOTER}`;
  bindDecision();
  enter("decision");
}

function decisionTotals() {
  let total = 0, minutes = 0, pending = 0;
  for (const it of state.order.items) {
    const c = state.choices[it.id];
    if (c === "today") { total += it.price; minutes += it.labor_minutes; }
    if (it.level === "deferrable" && !c) pending += 1;
  }
  return { total, minutes, pending };
}

function renderDecisionBar() {
  const { total, minutes, pending } = decisionTotals();
  const prev = Number(document.getElementById("dockTotal")?.dataset.v || 0);
  setDock(`<div class="grow"><div class="faint small">今天處理合計</div><div class="total" id="dockTotal" data-v="${prev}">${money(prev)}</div>
      <div class="faint small">施工約 ${minutes + 15} 分鐘（含品檢）</div></div>
    <button class="btn primary lg" id="confirmBtn" ${pending ? "disabled" : ""}>${pending ? `還有 ${pending} 項未選` : "確認送出"}</button>`);
  document.getElementById("confirmBtn").onclick = submitDecision;
  countUp(document.getElementById("dockTotal"), total);
}

function setChoice(id, c) {
  state.choices[id] = c;
  document.querySelectorAll(`[data-item="${id}"]`).forEach((x) => x.classList.toggle("on", x.dataset.c === c));
}

function bindDecision() {
  app.querySelectorAll("[data-item]").forEach((b) => (b.onclick = () => {
    setChoice(b.dataset.item, b.dataset.c);
    state.preset = null;
    app.querySelectorAll("[data-preset]").forEach((p) => p.classList.remove("on"));
    renderDecisionBar();
  }));
  app.querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => {
    state.preset = b.dataset.preset;
    for (const it of state.order.items) if (it.level === "deferrable") setChoice(it.id, b.dataset.preset === "all" ? "today" : "defer");
    app.querySelectorAll("[data-preset]").forEach((p) => p.classList.toggle("on", p === b));
    renderDecisionBar();
  }));
  app.querySelectorAll("[data-open]").forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    state.detail = Number(b.dataset.open);
    state.scrollY = window.scrollY;
    renderDetail();
    window.scrollTo(0, 0);
  }));
  renderDecisionBar();
}

// ---------- 證據頁（單一項目）----------
function renderDetail() {
  const o = state.order;
  const it = o.items.find((i) => i.id === state.detail);
  if (!it) { state.detail = null; return render(); }
  const lv = LEVEL[it.level];
  setHero({
    photo: it.photos[0] || o.vehicle.image_url, short: true,
    left: `<button id="backBtn">‹ 決策卡</button>`,
    right: `<span class="st">${it.photos.length ? `技師照片 ${it.photos.length} 張` : it.rule_type === "mileage" ? "依里程自動計算" : "技師現場檢查"}</span>`,
  });
  app.innerHTML = `
    <div class="card">
      <div class="ev-head"><img class="th" src="${esc(it.image_url)}" alt="">
        <div class="grow"><h2>${esc(it.name)}</h2><div class="faint">${esc(it.basis || "")}</div></div>
        <span class="badge ${lv.cls}">${esc(lv.zh)}</span></div>
      ${gaugeHtml(it)}
      ${it.photos.length ? `<div class="shots">${it.photos.map((p) => `<img src="${esc(p)}" alt="技師檢查照片" onclick="lightbox('${esc(p)}')">`).join("")}</div>` : ""}
      ${it.reason ? `<div class="note"><b>技師說明</b>${esc(it.reason)}</div>` : ""}
      <div class="explain"><p>${esc(it.explain_text)}</p>
        ${it.level === "deferrable" ? `<p><b style="color:var(--ink)">若延後：</b>${esc(it.defer_impact_text)}</p>` : ""}</div>
      ${it.level !== "normal" ? `<div class="cost"><div><div class="faint small">零件 ${money(it.part_price)}＋工資 ${money(it.labor_price)}</div>
        <div class="faint small">施工約 ${it.labor_minutes} 分鐘</div></div><span class="price">${money(it.price)}</span></div>` : ""}
      ${choiceSeg(it)}
    </div>${FOOTER}`;
  document.getElementById("backBtn").onclick = () => {
    state.detail = null;
    render();
    window.scrollTo(0, state.scrollY || 0);
  };
  app.querySelectorAll("[data-item]").forEach((b) => (b.onclick = () => { setChoice(b.dataset.item, b.dataset.c); state.preset = null; }));
  askDock(quickQuestions(it).slice(0, 3));
  bindAskDock(it);
  enter("detail-" + it.id, "slide-in");
}

async function submitDecision() {
  const o = state.order;
  const { total } = decisionTotals();
  const today = o.items.filter((i) => state.choices[i.id] === "today").map((i) => shortName(i.name));
  const defer = o.items.filter((i) => state.choices[i.id] === "defer").map((i) => shortName(i.name));
  const ok = await confirmDialog("確認今天的保養內容",
    `<p><b>今天處理：</b>${esc(today.join("、") || "無")}</p>
     <p class="mt-s"><b>延後並提醒：</b>${esc(defer.join("、") || "無")}</p>
     <p class="mt"><b style="font-size:20px">合計 ${money(total)}</b></p>`, "確認送出");
  if (!ok) return;
  try {
    await api("POST", "/api/customer/decision", { choices: state.choices }, { customer: true });
    toast("已送出，技師馬上開始施工", "ok");
    refresh(true);
  } catch (err) { toast(err.message, "err"); }
}

// ---------- 施工進度 ----------
function renderProgress(o) {
  mainHero(o);
  const today = o.items.filter((i) => i.customer_choice === "today");
  const done = today.filter((i) => i.work_status === "done").length;
  const events = o.events.slice().reverse();
  app.innerHTML = `
    <div class="card eta"><div class="faint">預估完成時間</div><div class="big">${hhmm(o.eta)}</div>
      <div class="muted small">已完成 ${done} / ${today.length} 項・每完成一項就更新</div>
      <div class="pbar"><span style="width:${today.length ? Math.round(done / today.length * 100) : 100}%"></span></div></div>
    <div class="card"><h2>施工項目</h2>
      ${today.length ? today.map((i) => `<div class="ck"><span class="ws ${i.work_status}">${i.work_status === "done" ? "✓" : ""}</span>
        <img src="${esc(i.image_url)}" alt=""><span class="grow">${esc(shortName(i.name))}</span>
        <span class="faint small">${{ pending: "等待中", in_progress: "施工中", done: "完成" }[i.work_status]}</span></div>`).join("")
        : `<p class="muted" style="margin:0">今天沒有需要更換的零件，品檢完成後即可交車。</p>`}</div>
    <div class="card"><h2>時間軸</h2><ul class="timeline">
      ${events.map((e, idx) => `<li class="${idx === 0 ? "now" : "done"}"><div>${esc(e.message)}</div><div class="t">${hhmm(e.time)}</div></li>`).join("")}</ul></div>${FOOTER}`;
  askDock(["還要等多久？", "今天換了哪些？", "總共多少錢？"]);
  bindAskDock();
  enter("progress");
}

// ---------- 交車摘要＋回廠提醒 ----------
async function renderSummary(o) {
  mainHero(o, "/static/img/delivery.jpg", "保養完成，可以交車了");
  setDock("");
  const s = await api("GET", "/api/customer/summary", undefined, { customer: true });
  const row = (i, extra) => `<div class="ck"><img src="${esc(i.image_url)}" alt="">
    <div class="grow"><b>${esc(shortName(i.name))}</b><div class="faint small">${extra}</div></div></div>`;
  const fmtDate = (d) => d.replaceAll("-", "/");
  app.innerHTML = `
    <div class="nochange"><h2>今天不用換：${s.normal.length} 項</h2>
      <p class="muted small" style="margin:0">${esc(s.normal.map((i) => shortName(i.name)).join("、"))} 狀況良好，我們沒有更換。照片與量測都已保留，下次回廠可以對照。</p></div>
    <div class="card"><div class="row between"><h2 style="margin:0">今天完成</h2><span class="faint">${s.done.length} 項</span></div>
      ${s.done.length ? s.done.map((i) => row(i, `${money(i.price)}・${esc(i.basis || "")}`)).join("") : `<p class="muted">今天沒有更換零件</p>`}
      <div class="cost"><span class="muted">合計</span><span class="price">${money(s.paid_total)}</span></div></div>
    ${s.deferred.length ? `<div class="card"><div class="row between"><h2 style="margin:0">延後項目，到時提醒你</h2><span class="faint">${s.deferred.length} 項</span></div>
      ${s.deferred.map((i) => row(i, i.reminder ? `建議 ${fmtDate(i.reminder.due_date)} 前${i.reminder.due_km ? `（或 ${i.reminder.due_km.toLocaleString()} km）` : ""}回廠` : "")).join("")}
      ${s.deferred[0].reminder ? `<div class="line-msg"><div class="who">LINE 提醒預覽（示意）</div>
        <div class="bubble">${esc(s.deferred[0].reminder.message)}</div></div>` : ""}</div>` : ""}
    <div class="card"><p class="small muted" style="margin:0">每一筆結論都附技師量測、照片與規則版本 ${esc(s.order.rule_version)}，完工時間 ${mdhm(s.order.completed_at)}。</p></div>${FOOTER}`;
  enter("summary");
}

// ---------- AI 服務專員 ----------
const chat = document.getElementById("chat");
const chatBg = document.getElementById("chatBg");
const chatBody = document.getElementById("chatBody");

function quickQuestions(item) {
  if (item) {
    const n = shortName(item.name);
    const qs = [`${n}為什麼${item.level === "normal" ? "不用換" : "要換"}？`];
    if (item.level !== "normal") qs.push(`${n}不換會怎樣？`, `${n}多少錢？`);
    qs.push(`${n}上次什麼時候換的？`);
    return qs;
  }
  const o = state.order;
  if (!o || !o.items.length) return ["這次會檢查哪些項目？", "檢查要多久？", "上次保養換了什麼？"];
  return ["哪些一定要今天換？", "總共多少錢？", "還要等多久？"];
}

function msgHtml(m) {
  const who = { customer: "", agent: "AI 服務專員", staff: "服務專員（真人）" }[m.role];
  const src = m.sources?.length ? `<div class="src">${m.sources.map((s) => `<span>${esc(s)}</span>`).join("")}</div>` : "";
  return `<div class="msg ${m.role}">${who ? `<div class="who">${who}</div>` : ""}${esc(m.content)}${src}</div>`;
}

async function loadChat() {
  const r = await api("GET", "/api/customer/chat", undefined, { customer: true });
  state.handoff = r.handoff_status;
  document.getElementById("chatSub").textContent = r.handoff_status
    ? (r.handoff_status === "waiting" ? "已通知服務專員，請稍候…" : "服務專員已加入對話") : "只根據本次工單與原廠規則回答";
  if (r.messages.length === state.chatCount) return;
  state.chatCount = r.messages.length;
  chatBody.innerHTML = r.messages.length ? r.messages.map(msgHtml).join("")
    : msgHtml({ role: "agent", content: "你好，我是 AI 服務專員。看不懂哪一項、想知道不換會怎樣，都可以直接問我。" });
  chatBody.scrollTop = chatBody.scrollHeight;
}

async function openChat(item = null, question = null) {
  if (item === null && state.detail) item = state.order.items.find((i) => i.id === state.detail) || null;
  state.chatOpen = true;
  chat.classList.remove("hidden");
  chatBg.classList.remove("hidden");
  document.body.classList.add("chat-on");
  document.getElementById("chatQuick").innerHTML = quickQuestions(item).map((q) => `<button type="button" class="btn">${esc(q)}</button>`).join("");
  document.querySelectorAll("#chatQuick button").forEach((b) => (b.onclick = () => ask(b.textContent)));
  state.chatCount = -1;
  await loadChat();
  if (question) ask(question);
}
function closeChat() { state.chatOpen = false; chat.classList.add("hidden"); chatBg.classList.add("hidden"); document.body.classList.remove("chat-on"); }

async function ask(text) {
  if (!text.trim()) return;
  chatBody.insertAdjacentHTML("beforeend", msgHtml({ role: "customer", content: text }) +
    `<div class="msg agent typing" id="typing">思考中…</div>`);
  chatBody.scrollTop = chatBody.scrollHeight;
  try {
    const r = await api("POST", "/api/customer/chat", { message: text }, { customer: true });
    document.getElementById("typing")?.remove();
    if (r.reply) {
      chatBody.insertAdjacentHTML("beforeend", msgHtml({ role: "agent", content: r.reply, sources: r.sources }));
      if (r.suggest_handoff && !state.handoff) {
        chatBody.insertAdjacentHTML("beforeend",
          `<div class="msg agent"><button class="btn sm primary" onclick="requestHandoff()">轉接服務專員</button></div>`);
      }
    }
    state.chatCount += r.reply ? 2 : 1;
    chatBody.scrollTop = chatBody.scrollHeight;
  } catch (err) {
    document.getElementById("typing")?.remove();
    toast(err.message, "err");
  }
}

async function requestHandoff() {
  try {
    await api("POST", "/api/customer/handoff", undefined, { customer: true });
    state.chatCount = -1;
    await loadChat();
    toast("已通知服務專員", "ok");
  } catch (err) { toast(err.message, "err"); }
}

document.getElementById("chatClose").onclick = closeChat;
chatBg.onclick = closeChat;
document.getElementById("handoffBtn").onclick = requestHandoff;
document.getElementById("chatForm").onsubmit = (e) => {
  e.preventDefault();
  const input = document.getElementById("chatText");
  const text = input.value;
  input.value = "";
  ask(text);
};

// ---------- 啟動與輪詢 ----------
let timer = null;
async function start() {
  if (!sessionStorage.getItem("custToken") || (qrToken && sessionStorage.getItem("custFor") !== qrToken)) {
    sessionStorage.removeItem("custToken");
    renderLogin();
    return;
  }
  try { await refresh(true); } catch (err) { showError(err); return; }
  clearInterval(timer);
  timer = setInterval(async () => {
    try {
      await refresh();
      if (state.chatOpen) await loadChat();
    } catch (e) { /* 網路暫時不穩，下次再試 */ }
  }, 3000);
}
start();
