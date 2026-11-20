// 技師端：工單列表 → 開始檢查 → 公里數（里程項目自動算）→ 只檢查需要動手的項目，一項一張大卡 → 送出 → 施工 → 品檢完成
const app = document.getElementById("app");
const S = (url) => api("GET", url, undefined, { staff: true });
const P = (url, body, method = "POST") => api(method, url, body, { staff: true });

const GROUPS = [
  { key: "inspect", zh: "待檢查", statuses: ["created", "inspecting"] },
  { key: "await", zh: "等車主決定", statuses: ["awaiting_customer"] },
  { key: "work", zh: "待施工／施工中", statuses: ["confirmed", "in_progress"] },
  { key: "done", zh: "已完工", statuses: ["completed"] },
];
// 常用原因：點一下就填入
const REASON_CHIPS = {
  輪胎: ["胎紋低於法規", "胎紋偏淺", "胎面不均勻磨損", "側壁龜裂"],
  煞車: ["來令片偏薄", "煞車盤有溝痕", "煞車異音"],
  電系: ["健康度偏低", "CCA 偏低", "冷車啟動較慢"],
  外觀: ["膠條硬化", "刮水有殘痕", "雨刷跳動"],
  油電系統: ["濾網積灰", "進風口堵塞"],
};
const state = { view: "list", tab: "inspect", orders: [], lastStatus: {}, order: null, step: "km" };

// ---------- 工單列表 ----------
function showList() { state.view = "list"; state.order = null; renderList(); }

async function pollOrders() {
  const orders = await S("/api/tech/work-orders");
  for (const o of orders) {
    const prev = state.lastStatus[o.id];
    if (prev === "awaiting_customer" && o.status === "confirmed") {
      toast(`${o.vehicle.plate} 車主已確認，可以開始施工`, "ok");
      o._flash = true;
    }
    if (prev === undefined && o.status === "created" && Object.keys(state.lastStatus).length) {
      toast(`新工單：${o.vehicle.plate}`, "ok");
    }
    state.lastStatus[o.id] = o.status;
  }
  state.orders = orders;
  if (state.view === "list") renderList();
  if (state.view === "order" && state.order) {
    const cur = orders.find((o) => o.id === state.order.id);
    if (cur && cur.status !== state.order.status && !["inspecting"].includes(state.order.status)) openOrder(cur.id);
  }
}

function renderList() {
  const tabs = GROUPS.map((g) => {
    const n = state.orders.filter((o) => g.statuses.includes(o.status)).length;
    return `<button class="tab ${state.tab === g.key ? "on" : ""}" data-tab="${g.key}">${g.zh}
      <span class="count ${n ? "" : "gray"}">${n}</span></button>`;
  }).join("");
  const g = GROUPS.find((x) => x.key === state.tab);
  const list = state.orders.filter((o) => g.statuses.includes(o.status));
  app.innerHTML = `<div class="tabs">${tabs}</div>
    ${list.length ? `<div class="grid2">${list.map((o) => `
      <div class="card order-card ${o._flash ? "flash" : ""}" data-id="${o.id}">
        <img src="${esc(o.vehicle.image_url)}" alt=""><div class="grow"><div class="row between"><span class="plate">${esc(o.vehicle.plate)}</span>
          <span class="badge ${o.status === "completed" ? "gray" : "info"}">${esc(o.status_zh)}</span></div>
        <div class="mt"><b>${esc(o.vehicle.model)}</b></div>
        <div class="faint mt-s">工單 #${o.id}・${esc(o.vehicle.owner_name)}・${mdhm(o.created_at)}
          ${o.status === "inspecting" ? `・已檢查 ${o.progress.checked}/${o.progress.total}` : ""}
          ${o.eta && o.status !== "completed" ? `・預估 ${hhmm(o.eta)} 完成` : ""}</div></div></div>`).join("")}</div>`
      : `<div class="card empty">目前沒有「${g.zh}」的工單</div>`}`;
  enterOnce(app, "tech", "list-" + state.tab);
  app.querySelectorAll(".tab").forEach((b) => (b.onclick = () => { state.tab = b.dataset.tab; renderList(); }));
  app.querySelectorAll(".order-card").forEach((c) => (c.onclick = () => openOrder(Number(c.dataset.id))));
}

// ---------- 單一工單 ----------
async function openOrder(id, keepStep = false) {
  state.view = "order";
  const o = await S(`/api/tech/work-orders/${id}`);
  state.order = o;
  state.lastStatus[o.id] = o.status;
  if (!keepStep) state.step = o.current_km == null ? "km" : (nextUnchecked(o)?.id ?? "submit");
  if (o.status === "created") renderStart(o);
  else if (o.status === "inspecting") renderInspection();
  else if (o.status === "awaiting_customer") renderAwaiting(o);
  else renderWork(o);
}

function headerHtml(o) {
  return `<div class="card"><div class="row between wrap-row">
    <div class="grow"><div class="row wrap-row" style="gap:6px 10px"><span class="plate">${esc(o.vehicle.plate)}</span><b>${esc(o.vehicle.model)}</b></div>
      <div class="faint mt-s">工單 #${o.id}・車主 ${esc(o.vehicle.owner_name)}${o.current_km ? `・${o.current_km.toLocaleString()} km` : ""}</div></div>
    <span class="badge info">${esc(o.status_zh)}</span></div></div>`;
}

function renderStart(o) {
  app.innerHTML = headerHtml(o) + `<div class="card" style="text-align:center;padding:44px">
    <h2>準備開始檢查</h2>
    <p class="muted mt">流程：輸入公里數 → 量測與目視檢查（一項一張卡，拍照、填數值）→ 送出。機油、濾網等里程項目系統自動計算，不用動手。</p>
    <button class="btn primary lg mt" id="startBtn">開始檢查</button></div>`;
  document.getElementById("startBtn").onclick = async () => {
    try { await P(`/api/tech/work-orders/${o.id}/start`); openOrder(o.id); } catch (e) { toast(e.message, "err"); }
  };
}

const techItems = (o) => o.items.filter((i) => i.rule_type !== "mileage");
const autoItems = (o) => o.items.filter((i) => i.rule_type === "mileage");
const nextUnchecked = (o, after = null) => {
  const list = techItems(o);
  const start = after ? list.findIndex((i) => i.id === after) + 1 : 0;
  return list.slice(start).find((i) => !i.checked) || list.find((i) => !i.checked);
};

function renderInspection() {
  const o = state.order;
  const tItems = techItems(o);
  const done = tItems.filter((i) => i.checked).length;
  const ready = o.current_km != null && done === tItems.length;
  const nav = `<div class="card steps-nav">
      <div class="step ${state.step === "km" ? "on" : ""}" data-step="km"><span>1</span>公里數
        <span class="st ${o.current_km != null ? "normal" : ""}"></span></div>
      ${tItems.map((i, idx) => `<div class="step ${state.step === i.id ? "on" : ""}" data-step="${i.id}">
        <img src="${esc(i.image_url)}" alt=""><span>${esc(i.name.replace(/（.*?）/, ""))}</span>
        <span class="st ${i.checked ? i.level : ""}"></span></div>`).join("")}
      <div class="step auto">＋ ${autoItems(o).length} 項里程項目自動計算</div>
      <div class="mt" style="padding:6px">
        <div class="faint mb">已完成 ${done + (o.current_km != null ? 1 : 0)} / ${tItems.length + 1}</div>
        <button class="btn primary block" id="submitBtn" ${ready ? "" : "disabled"}>送出給車主</button></div></div>`;
  let main = "";
  if (state.step === "km") main = kmCard(o);
  else main = itemCard(o.items.find((i) => i.id === state.step));
  app.innerHTML = headerHtml(o) + `<div class="insp">${nav}<div>${main}</div></div>`;
  enterOnce(app, "tech", "insp-" + o.id);
  enterOnce(app.querySelector(".insp > div:last-child"), "tech-step", `${o.id}-${state.step}`, "slide-in");
  // 手機上步驟列是橫向滑動的，把目前這一步捲到中間
  const on = app.querySelector(".steps-nav .step.on");
  const navEl = app.querySelector(".steps-nav");
  if (on && navEl && navEl.scrollWidth > navEl.clientWidth) navEl.scrollLeft = on.offsetLeft - navEl.clientWidth / 2 + on.offsetWidth / 2;

  app.querySelectorAll(".step[data-step]").forEach((s) => (s.onclick = () => {
    state.step = s.dataset.step === "km" ? "km" : Number(s.dataset.step);
    renderInspection();
  }));
  document.getElementById("submitBtn").onclick = doSubmit;
  if (state.step === "km") bindKm(); else bindItem();
}

// 公里數＋里程項目自動結果
function kmCard(o) {
  const lastKm = Math.max(0, ...o.items.map((i) => i.last_km || 0));
  const autos = autoItems(o);
  return `<div class="card big-card">
    <h2>目前公里數</h2><p class="faint mt-s">上次保養紀錄 ${lastKm.toLocaleString()} km</p>
    <div class="km-in row mt"><input class="input" id="km" type="number" inputmode="numeric" min="0" max="999999" step="1" value="${o.current_km ?? ""}" placeholder="0"><span class="unit muted" style="font-size:22px">km</span></div>
    <button class="btn primary lg mt" id="kmBtn">確認，下一步 →</button>
    ${o.current_km != null ? `<h3 class="mt" style="margin-top:24px">里程項目（系統自動計算）</h3>
      ${autos.map((i) => `<div class="auto-row"><img src="${esc(i.image_url)}" alt=""><span class="grow"><b>${esc(i.name)}</b>
        <div class="faint">${esc(i.basis || "")}</div></span>
        <span class="badge ${i.level}">${esc(i.level_zh || "")}</span>
        <button class="btn sm" data-must="${i.id}">${i.tech_status === "must" ? "取消異常" : "現場異常"}</button></div>`).join("")}
      <p class="faint mt">若現場發現漏油、異音等狀況，按「現場異常」會改為必須處理。</p>` : ""}</div>`;
}

// 數字欄位：擋掉負號、科學記號，貼上的負數也會被清掉
function guardNumber(input, { integer = false } = {}) {
  if (!input) return;
  input.addEventListener("keydown", (e) => {
    if (["-", "+", "e", "E"].includes(e.key) || (integer && [".", ","].includes(e.key))) e.preventDefault();
  });
  input.addEventListener("input", () => {
    let v = input.value.replace(/-/g, "");
    if (integer) v = v.replace(/[.,].*$/, "");
    if (v !== input.value) input.value = v;
  });
}

function minKm(o) {
  return Math.max(0, ...o.items.map((i) => i.last_km || 0));
}

function bindKm() {
  const input = document.getElementById("km");
  guardNumber(input, { integer: true });
  input.focus();
  const go = async () => {
    if (input.value === "") { toast("請輸入公里數", "err"); return; }
    const km = Number(input.value);
    if (!Number.isInteger(km) || km < 0) { toast("公里數要是 0 以上的整數", "err"); return; }
    if (km > 999999) { toast("公里數不能超過 999,999 km", "err"); return; }
    const min = minKm(state.order);
    if (km < min) { toast(`公里數不能小於上次保養紀錄的 ${min.toLocaleString()} km`, "err"); return; }
    try {
      await P(`/api/tech/work-orders/${state.order.id}/mileage`, { current_km: Number(input.value) }, "PUT");
      state.step = "km";
      await openOrder(state.order.id, true);
      state.step = nextUnchecked(state.order)?.id ?? "km";
      renderInspection();
    } catch (e) { toast(e.message, "err"); }
  };
  document.getElementById("kmBtn").onclick = go;
  input.onkeydown = (e) => { if (e.key === "Enter") go(); };
  app.querySelectorAll("[data-must]").forEach((b) => (b.onclick = async () => {
    const it = state.order.items.find((i) => i.id === Number(b.dataset.must));
    let reason = it.reason;
    if (it.tech_status !== "must") {
      reason = prompt("請輸入異常原因（會顯示給車主）", it.reason || "");
      if (reason === null) return;
    }
    try {
      await P(`/api/tech/items/${it.id}`, { tech_status: it.tech_status === "must" ? null : "must", reason }, "PUT");
      await openOrder(state.order.id, true);
    } catch (e) { toast(e.message, "err"); }
  }));
}

// 單項大卡：拍照 → 量測／判定 → 原因 → 下一項
function itemCard(it) {
  const chips = REASON_CHIPS[it.category] || [];
  let input = "";
  if (it.rule_type === "measure") {
    input = `<div class="measure-in"><input class="input" id="mv" type="number" min="0" step="0.1" inputmode="decimal" value="${it.measured_value ?? ""}" placeholder="0.0">
      <span class="unit">${esc(it.unit)}</span></div>
      <p class="faint mt-s">安全門檻 ${it.safe_min} ${esc(it.unit)}・預警 ${it.warn_min} ${esc(it.unit)}${it.last_km ? "" : ""}</p>`;
  } else {
    const v = it.tech_status || "normal";
    input = `<div class="pick">${[["normal", "正常"], ["suggest", "建議更換"], ["must", "必須更換"]].map(([k, zh]) =>
      `<button data-v="${k}" class="${v === k ? "on" : ""}">${zh}</button>`).join("")}</div>`;
  }
  return `<div class="card big-card">
    <div class="head"><img src="${esc(it.image_url)}" alt=""><div><h2>${esc(it.name)}</h2>
      <div class="faint">${it.safety_critical ? "安全關鍵項目・" : ""}${it.rule_type === "measure" ? "請量測後輸入數值" : "請目視檢查"}</div></div></div>
    <div class="shoot">${it.photos.map((p) => `<img src="${esc(p)}" alt="" onclick="lightbox('${esc(p)}')">`).join("")}
      <label><span style="font-size:28px;line-height:1">＋</span><span>拍照</span><input type="file" accept="image/*" capture="environment" id="photo"></label></div>
    ${input}
    <div class="field mt" style="margin-top:18px"><label>給車主的說明（選填）</label>
      <input class="input" id="reason" value="${esc(it.reason || "")}" placeholder="例如：胎紋 1.4 mm，低於法規 1.6 mm">
      ${chips.length ? `<div class="chips">${chips.map((c) => `<button type="button">${esc(c)}</button>`).join("")}</div>` : ""}</div>
    ${it.checked ? `<div class="result"><span class="badge ${it.level}">${esc(it.level_zh)}</span><span class="muted small">${esc(it.basis || "")}</span></div>` : ""}
    <div class="row between mt" style="margin-top:20px"><span class="faint">完成後自動跳到下一項</span>
      <button class="btn primary lg" id="saveBtn">完成，下一項 →</button></div></div>`;
}

function bindItem() {
  const it = state.order.items.find((i) => i.id === state.step);
  let status = it.tech_status || "normal";
  app.querySelectorAll(".pick button").forEach((b) => (b.onclick = () => {
    status = b.dataset.v;
    app.querySelectorAll(".pick button").forEach((x) => x.classList.toggle("on", x === b));
  }));
  const reason = document.getElementById("reason");
  app.querySelectorAll(".chips button").forEach((b) => (b.onclick = () => {
    reason.value = reason.value ? `${reason.value}，${b.textContent}` : b.textContent;
  }));
  guardNumber(document.getElementById("mv"));
  document.getElementById("mv")?.focus();
  document.getElementById("photo").onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      await api("POST", `/api/tech/items/${it.id}/photos`, undefined, { staff: true, form });
      const keep = { mv: document.getElementById("mv")?.value, reason: reason.value, status };
      await openOrder(state.order.id, true);
      if (keep.mv !== undefined) document.getElementById("mv").value = keep.mv;
      document.getElementById("reason").value = keep.reason;
      toast("照片已上傳", "ok");
    } catch (err) { toast(err.message, "err"); }
  };
  const save = async () => {
    const body = { reason: reason.value.trim() || null };
    const mv = document.getElementById("mv");
    if (mv) {
      if (mv.value === "") { toast("請輸入量測值", "err"); return; }
      if (Number(mv.value) < 0 || Number.isNaN(Number(mv.value))) { toast("量測值不能是負數", "err"); return; }
      body.measured_value = Number(mv.value);
    } else {
      body.tech_status = status;
    }
    try {
      const saved = await P(`/api/tech/items/${it.id}`, body, "PUT");
      if (saved.level !== "normal") toast(`${saved.name}：${saved.level_zh}`, saved.level === "immediate" ? "err" : "");
      await openOrder(state.order.id, true);
      const next = nextUnchecked(state.order, it.id);
      state.step = next ? next.id : it.id;
      renderInspection();
      if (!next) toast("全部檢查完成，可以送出給車主了", "ok");
    } catch (err) { toast(err.message, "err"); }
  };
  document.getElementById("saveBtn").onclick = save;
  document.getElementById("mv")?.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
}

async function doSubmit() {
  const o = state.order;
  const c = { immediate: 0, deferrable: 0, normal: 0 };
  o.items.forEach((i) => i.level && c[i.level]++);
  const ok = await confirmDialog("送出給車主？",
    `必須處理 <b>${c.immediate}</b> 項、可延後 <b>${c.deferrable}</b> 項、今天不用換 <b>${c.normal}</b> 項。<br>送出後車主手機會立即出現決策卡。`, "送出");
  if (!ok) return;
  try {
    await P(`/api/tech/work-orders/${o.id}/submit`);
    toast("已送出，等待車主決定", "ok");
    openOrder(o.id);
  } catch (e) { toast(e.message, "err"); }
}

// ---------- 等車主決定 ----------
function renderAwaiting(o) {
  const order = ["immediate", "deferrable", "normal"];
  const items = o.items.slice().sort((a, b) => order.indexOf(a.level) - order.indexOf(b.level));
  app.innerHTML = headerHtml(o) + `<div class="card"><div class="row"><span class="pulse"></span><b>等車主在手機上決定</b></div>
      <p class="faint mt-s">車主確認後這裡會自動切換到施工畫面並通知你。</p></div>
    <div class="grid2">${items.map((it) => `<div class="item lv-${it.level}"><div class="row">
      <img class="thumb" src="${esc(it.image_url)}" alt=""><div class="grow"><b>${esc(it.name)}</b>
      <div class="basis">${esc(it.basis || "")}</div></div><span class="badge ${it.level}">${esc(it.level_zh)}</span></div></div>`).join("")}</div>`;
  enterOnce(app, "tech", "await-" + o.id);
}

// ---------- 施工 ----------
function renderWork(o) {
  const today = o.items.filter((i) => i.customer_choice === "today");
  const defer = o.items.filter((i) => i.customer_choice === "defer");
  const allDone = today.every((i) => i.work_status === "done");
  const done = o.status === "completed";
  app.innerHTML = headerHtml(o) + `
    <div class="grid3">
      <div class="card"><div class="faint">今天施工</div><div class="big-num">${today.length} 項</div></div>
      <div class="card"><div class="faint">已完成</div><div class="big-num">${today.filter((i) => i.work_status === "done").length} 項</div></div>
      <div class="card"><div class="faint">預估完成</div><div class="big-num">${hhmm(o.eta)}</div></div></div>
    <div class="card"><h2>施工項目</h2>
      ${today.length ? today.map((i) => `<div class="item"><div class="row">
        <img class="thumb" src="${esc(i.image_url)}" alt=""><div class="grow"><b>${esc(i.name)}</b>
        <div class="faint">標準工時 ${i.labor_minutes} 分・${esc(i.basis || "")}</div></div>
        ${i.work_status === "pending" && !done ? `<button class="btn dark lg" data-start="${i.id}">開始</button>` : ""}
        ${i.work_status === "in_progress" ? `<button class="btn primary lg" data-done="${i.id}">完成</button>` : ""}
        ${i.work_status === "done" ? `<span class="badge normal">已完成</span>` : ""}</div></div>`).join("")
        : `<p class="muted">車主沒有選擇今天施工的項目，品檢後即可交車。</p>`}</div>
    ${defer.length ? `<div class="card"><h2>車主選擇延後（交車後自動建立回廠提醒）</h2>${defer.map((i) =>
      `<div class="faint mt-s">・${esc(i.name)}（${esc(i.basis || "")}）</div>`).join("")}</div>` : ""}
    ${done ? `<div class="card" style="text-align:center"><h2>已完工交車</h2><p class="muted mt-s">完工時間 ${mdhm(o.completed_at)}</p></div>`
      : `<div class="card row between"><span class="muted">全部完成後按品檢完成，車主會收到交車摘要</span>
      <button class="btn primary lg" id="completeBtn" ${allDone ? "" : "disabled"}>品檢完成、交車</button></div>`}`;
  app.querySelectorAll("[data-start]").forEach((b) => (b.onclick = () => act(`/api/tech/items/${b.dataset.start}/start`)));
  app.querySelectorAll("[data-done]").forEach((b) => (b.onclick = () => act(`/api/tech/items/${b.dataset.done}/done`)));
  const c = document.getElementById("completeBtn");
  if (c) c.onclick = () => act(`/api/tech/work-orders/${o.id}/complete`, "已完工，車主已收到交車摘要");
}

async function act(url, msg) {
  try {
    const o = await P(url);
    state.order = o;
    state.lastStatus[o.id] = o.status;
    renderWork(o);
    if (msg) toast(msg, "ok");
  } catch (e) { toast(e.message, "err"); }
}

// ---------- 啟動 ----------
(async () => {
  await ensureStaff();
  await pollOrders();
  setInterval(() => pollOrders().catch(() => {}), 3000);
})();
