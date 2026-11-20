// 管理平台：接待建單（專屬 QR）、工單與專員 30 秒說明稿、轉接中心、回廠提醒、零件與規則、示範工具
const view = document.getElementById("view");
const S = (url) => api("GET", url, undefined, { staff: true });
const P = (url, body, method = "POST") => api(method, url, body, { staff: true });
const state = { tab: "reception", info: null, handoffs: [], handoffIds: new Set(), loadedOnce: false,
  activeHandoff: null, msgCount: -1, orderStatus: {}, detailId: null };

document.querySelectorAll("#tabs .tab").forEach((b) => (b.onclick = () => go(b.dataset.tab)));

function go(tab) {
  state.tab = tab;
  state.detailId = null;
  document.querySelectorAll("#tabs .tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  Promise.resolve(({ reception, orders, handoffs, reminders, parts, demo })[tab]()).then(() => stagger(view));
}

async function qrImg(orderId) {
  const res = await api("GET", `/api/admin/work-orders/${orderId}/qr.png?ts=${Date.now()}`, undefined, { staff: true, raw: true });
  return URL.createObjectURL(await res.blob());
}

// ---------- 接待建單 ----------
async function reception() {
  const vehicles = await S("/api/admin/vehicles");
  view.innerHTML = `<div class="grid2">
    <div class="card no-print"><h2>接待建單</h2>
      <p class="muted small mb">輸入車牌建立工單，系統產生這台車專屬的 QR Code，交給車主掃描即可。</p>
      <form id="newOrder">
        <div class="field"><label>車牌</label>
          <input class="input big" name="plate" list="plates" placeholder="ABC-1234" required autocomplete="off">
          <datalist id="plates">${vehicles.map((v) => `<option value="${esc(v.plate)}">${esc(v.owner_name)}・${esc(v.model)}</option>`).join("")}</datalist></div>
        <div id="vehicleInfo" class="faint mb"></div>
        <div id="newCar" class="hidden"><div class="grid2">
          <div class="field"><label>車主姓名（新車）</label><input class="input" name="owner_name"></div>
          <div class="field"><label>車主電話</label><input class="input" name="owner_phone"></div></div></div>
        <button class="btn primary block" type="submit">建立工單，產生 QR</button>
      </form>
      <div id="netBox" class="mt"></div></div>
    <div class="card qr-box" id="qrResult"><div class="empty">建立工單後，專屬 QR Code 會顯示在這裡，可直接列印交給車主</div></div></div>`;

  renderNet();
  const form = document.getElementById("newOrder");
  form.plate.oninput = () => {
    const v = vehicles.find((x) => x.plate === form.plate.value.trim().toUpperCase());
    document.getElementById("vehicleInfo").textContent = v ? `${v.owner_name}・${v.owner_phone}・${v.model}` : "";
    document.getElementById("newCar").classList.toggle("hidden", !!v || !form.plate.value.trim());
  };
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await P("/api/admin/work-orders", {
        plate: form.plate.value, owner_name: form.owner_name.value || null, owner_phone: form.owner_phone.value || null });
      await showQr(r.order, r.customer_url, document.getElementById("qrResult"));
      state.orderStatus[r.order.id] = r.order.status;
      toast(`已建立工單 #${r.order.id}`, "ok");
    } catch (err) { toast(err.message, "err"); }
  };
}

// ---------- 手機連線檢查 ----------
async function renderNet(net) {
  const box = document.getElementById("netBox");
  if (!box) return;
  net = net || await S("/api/admin/network");
  const problems = [];
  if (net.points_to_localhost) problems.push("QR 指向 localhost，手機一定連不上。請從下方選一個區網網址。");
  if (net.stale_env) problems.push(`設定裡的公開網址 ${esc(net.stale_env)} 已失效，已自動改用區網網址。要讓不同網路的朋友測試，請重開 cloudflared 並用它的新網址打開管理平台。`);
  if (net.tunnel_alive === false) problems.push(`這個公開網址已經失效（cloudflared 關掉或重開過，每次重開網址都會變）。請重新執行 cloudflared，用它新給的網址打開管理平台；若 .env 有填 PUBLIC_BASE_URL，請清空或換成新網址後重啟。`);
  if (net.lan_listening === false) problems.push("伺服器沒有對區網開放：請關掉後用 <code>start.bat</code>（或 uvicorn 加上 <code>--host 0.0.0.0</code>）重新啟動。");
  const ok = !problems.length;
  box.innerHTML = `<div class="note">
    <div class="row between"><b style="font-size:13px;color:var(--ink)">手機連線檢查</b>
      <span class="badge ${ok ? "info" : "gray"} dot">${ok ? (net.tunnel ? "公開網址" : "伺服器已對區網開放") : "需要處理"}</span></div>
    <div class="mt-s small">QR 會連到 <b>${esc(net.base)}</b>${net.source === "manual" ? "（手動指定）" : net.source === "env" ? "（.env 設定）" : "（自動偵測）"}</div>
    ${problems.map((p) => `<div class="small mt-s" style="color:var(--red)">${p}</div>`).join("")}
    ${!net.tunnel && net.candidates.length > 1 ? `<div class="mt-s small">偵測到多個網路，請選手機連的那個 Wi-Fi：</div>
      <div class="chips">${net.candidates.map((c) => `<button type="button" data-base="${esc(c.url)}" ${c.url === net.base ? 'style="outline:2px solid var(--ink)"' : ""}>${esc(c.ip)}${c.virtual ? "（虛擬網卡）" : ""}</button>`).join("")}
      ${net.source === "manual" ? `<button type="button" data-base="">恢復自動</button>` : ""}</div>` : ""}
    <details class="more"><summary>手機還是打不開？</summary>
      <p>1. 手機和電腦連同一個 Wi-Fi（不要用訪客網路，也不要開手機行動數據）。</p>
      <p>2. 第一次啟動時 Windows 會問是否允許 Python 連線，要勾「私人網路」。若當時按了取消，右鍵用系統管理員身分執行 <code>開放防火牆.bat</code>。</p>
      <p>3. 先用手機瀏覽器直接打開 <b>${esc(net.base)}/c/</b>，能看到頁面再掃 QR。</p>
      <p>4. 不在同一個網路（例如給朋友測試）：用 cloudflared 產生 https 網址，填進 .env 的 PUBLIC_BASE_URL。</p></details></div>`;
  box.querySelectorAll("[data-base]").forEach((b) => (b.onclick = async () => {
    const r = await P("/api/admin/network", { base: b.dataset.base }, "PUT");
    renderNet(r);
    toast("已切換，之後產生的 QR 都會用這個網址", "ok");
  }));
}

async function showQr(order, url, box) {
  const src = await qrImg(order.id);
  box.innerHTML = `<div class="row between no-print"><span class="badge info">工單 #${order.id}</span>
      <button class="btn sm" onclick="window.print()">列印 QR 卡</button></div>
    <h2 class="mt">${esc(order.vehicle.owner_name)}，歡迎回廠</h2>
    <p class="faint">${esc(order.vehicle.plate)}・${esc(order.vehicle.model)}</p>
    <img class="qr mt" src="${src}" alt="QR Code">
    <p class="mt"><b>用手機掃描，確認車牌就能即時看到愛車的檢查結果</b></p>
    <p class="faint mt-s small">等待時可以隨時問 AI 服務專員</p>
    <p class="faint mt small no-print" style="word-break:break-all"><a href="${esc(url)}" target="_blank">${esc(url)}</a></p>`;
}

// ---------- 工單與說明稿 ----------
async function orders() {
  if (state.detailId) return orderDetail(state.detailId);
  const list = await S("/api/admin/work-orders");
  const badge = (s) => (s === "completed" ? "gray" : "info");
  view.innerHTML = `<div class="card"><div class="row between"><h2>工單</h2><span class="faint">點一列查看專員說明稿與細節</span></div>
    <table class="tbl"><thead><tr><th>#</th><th>車牌</th><th>車主</th><th>狀態</th><th>公里數</th>
      <th>建立</th><th>預估完成</th><th>說明稿</th><th>轉接</th></tr></thead><tbody>
    ${list.map((o) => `<tr class="clickable" data-id="${o.id}"><td>${o.id}</td><td><span class="plate">${esc(o.vehicle.plate)}</span></td>
      <td>${esc(o.vehicle.owner_name)}</td><td><span class="badge ${badge(o.status)}">${esc(o.status_zh)}</span></td>
      <td>${o.current_km ? o.current_km.toLocaleString() : "—"}</td><td>${mdhm(o.created_at)}</td><td>${o.status === "completed" ? "—" : hhmm(o.eta)}</td>
      <td>${o.brief ? `<span class="badge info">已備好</span>` : ""}</td>
      <td>${o.waiting_handoffs ? `<span class="badge info dot">等待中</span>` : ""}</td></tr>`).join("")}
    </tbody></table>${list.length ? "" : `<div class="empty">還沒有工單，請先到「接待建單」</div>`}</div>`;
  view.querySelectorAll("tr[data-id]").forEach((tr) => (tr.onclick = () => orderDetail(Number(tr.dataset.id))));
}

async function orderDetail(id) {
  await orderDetailRender(id);
  stagger(view);
}
async function orderDetailRender(id) {
  state.detailId = id;
  const o = await S(`/api/admin/work-orders/${id}`);
  const lv = ["immediate", "deferrable", "normal"];
  const items = (o.items || []).filter((i) => i.level).sort((a, b) => lv.indexOf(a.level) - lv.indexOf(b.level));
  view.innerHTML = `<button class="btn sm mb" id="back">← 回工單列表</button>
    <div class="card"><div class="row between wrap-row"><div class="row"><span class="plate">${esc(o.vehicle.plate)}</span>
      <b>${esc(o.vehicle.owner_name)}・${esc(o.vehicle.model)}</b></div><span class="badge info">${esc(o.status_zh)}</span></div>
      ${stepsHtml(o.status_step)}</div>
    <div class="detail">
      <div>
        <div class="card"><div class="row between"><h2>專員 30 秒說明稿</h2>
          ${o.brief ? `<div class="row"><button class="btn sm" id="copyBrief">複製</button><button class="btn sm" id="regenBrief">重新產生</button></div>` : ""}</div>
          ${o.brief ? `<div class="brief">${esc(o.brief)}</div>
            <p class="faint mt-s">AI 依檢查結果產生，專員確認後再對車主說明；分級與數字以規則引擎為準。</p>`
            : `<p class="muted">技師檢查完成送出後，這裡會自動產生給專員的口頭說明稿。</p>`}</div>
        ${items.length ? `<div class="card"><h2>檢查結果</h2>${items.map((it) => `<div class="item lv-${it.level}"><div class="row">
          <img class="thumb" src="${esc(it.image_url)}" alt=""><div class="grow"><b>${esc(it.name)}</b>
          <div class="basis">${esc(it.basis || "")}${it.customer_choice ? `・車主選擇：${it.customer_choice === "today" ? "今天換" : "延後"}` : ""}</div></div>
          <span class="badge ${it.level}">${esc(it.level_zh)}</span></div></div>`).join("")}</div>` : ""}
      </div>
      <div>
        <div class="card qr-box" id="qrBox"></div>
        <div class="card"><h2>時間軸</h2><ul class="timeline">${o.events.slice().reverse().map((e, i) =>
          `<li class="${i === 0 ? "now" : "done"}"><div>${esc(e.message)}</div><div class="t">${hhmm(e.time)}</div></li>`).join("")}</ul></div>
      </div></div>`;
  document.getElementById("back").onclick = () => { state.detailId = null; orders(); };
  await showQr(o, o.customer_url, document.getElementById("qrBox"));
  document.getElementById("qrBox").insertAdjacentHTML("beforeend",
    `<button class="btn sm mt no-print" id="regenQr">QR 遺失或被鎖定？重新產生</button>`);
  document.getElementById("regenQr").onclick = async () => {
    const ok = await confirmDialog("重新產生 QR？", "舊的 QR 會立即失效，並解除登入鎖定。", "重新產生");
    if (!ok) return;
    await P(`/api/admin/work-orders/${id}/regenerate-qr`);
    orderDetail(id);
  };
  document.getElementById("copyBrief")?.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(o.brief); toast("已複製", "ok"); } catch (e) { toast("無法複製，請手動選取", "err"); }
  });
  document.getElementById("regenBrief")?.addEventListener("click", async () => {
    try { await P(`/api/admin/work-orders/${id}/brief`); orderDetail(id); toast("已重新產生", "ok"); } catch (e) { toast(e.message, "err"); }
  });
}

// 檢查完成 → 通知專員說明稿已備好
async function pollOrders() {
  const list = await S("/api/admin/work-orders");
  for (const o of list) {
    const prev = state.orderStatus[o.id];
    if (prev && prev !== o.status && o.status === "awaiting_customer") {
      toast(`${o.vehicle.plate} 檢查完成，專員說明稿已備好`, "ok");
    }
    state.orderStatus[o.id] = o.status;
  }
}

// ---------- 轉接中心 ----------
async function pollHandoffs() {
  const list = await S("/api/admin/handoffs");
  const waiting = list.filter((h) => h.status === "waiting").length;
  const c = document.getElementById("hCount");
  c.textContent = list.length;
  c.className = "count " + (waiting ? "" : "gray");
  for (const h of list) {
    if (!state.handoffIds.has(h.id)) {
      if (state.loadedOnce) toast(`${h.plate} ${h.owner_name} 要求轉接真人`, "ok");
      state.handoffIds.add(h.id);
    }
  }
  state.loadedOnce = true;
  state.handoffs = list;
  if (state.tab === "handoffs") {
    renderHandoffList();
    if (state.activeHandoff) await loadConversation();
  }
}

function handoffs() {
  view.innerHTML = `<div class="hand">
    <div class="card hand-list"><h2>轉接請求</h2><div id="hList"></div></div>
    <div class="card conv" id="conv"><div class="empty">選擇左側的轉接請求，查看車主與 AI 的對話並回覆</div></div></div>`;
  renderHandoffList();
  if (state.activeHandoff) openHandoff(state.activeHandoff.id);
}

function renderHandoffList() {
  const box = document.getElementById("hList");
  if (!box) return;
  box.innerHTML = state.handoffs.length ? state.handoffs.map((h) => `
    <div class="h ${state.activeHandoff?.id === h.id ? "on" : ""}" data-h="${h.id}">
      <div class="row between"><span class="plate">${esc(h.plate)}</span>
        <span class="badge ${h.status === "waiting" ? "info dot" : "gray"}">${h.status === "waiting" ? "等待中" : "處理中"}</span></div>
      <div class="faint mt-s">${esc(h.owner_name)}・工單 ${esc(h.order_status_zh)}・${hhmm(h.created_at)}</div></div>`).join("")
    : `<div class="empty">目前沒有轉接請求</div>`;
  box.querySelectorAll("[data-h]").forEach((el) => (el.onclick = () => openHandoff(Number(el.dataset.h))));
}

async function openHandoff(id) {
  state.activeHandoff = state.handoffs.find((h) => h.id === id);
  state.msgCount = -1;
  if (!state.activeHandoff) return;
  renderHandoffList();
  const h = state.activeHandoff;
  document.getElementById("conv").innerHTML = `
    <div class="row between mb"><div><b>${esc(h.plate)}・${esc(h.owner_name)}</b>
      <div class="faint">工單 #${h.work_order_id}・${esc(h.order_status_zh)}</div></div>
      <button class="btn sm" id="closeH">結束對話</button></div>
    <div class="conv-body" id="convBody"></div>
    <form class="row mt" id="replyForm"><input class="input grow" id="replyText" placeholder="回覆車主（會直接顯示在車主手機）" autocomplete="off">
      <button class="btn primary" type="submit">送出</button></form>`;
  document.getElementById("replyForm").onsubmit = async (e) => {
    e.preventDefault();
    const t = document.getElementById("replyText");
    if (!t.value.trim()) return;
    try {
      await P(`/api/admin/handoffs/${h.id}/reply`, { content: t.value });
      t.value = "";
      await loadConversation();
    } catch (err) { toast(err.message, "err"); }
  };
  document.getElementById("closeH").onclick = async () => {
    await P(`/api/admin/handoffs/${h.id}/close`);
    state.activeHandoff = null;
    await pollHandoffs();
    handoffs();
  };
  await loadConversation();
}

async function loadConversation() {
  const h = state.activeHandoff;
  const body = document.getElementById("convBody");
  if (!h || !body) return;
  const msgs = await S(`/api/admin/work-orders/${h.work_order_id}/messages`);
  if (msgs.length === state.msgCount) return;
  state.msgCount = msgs.length;
  const who = { customer: "車主", agent: "AI 服務專員", staff: "你（服務專員）" };
  body.innerHTML = msgs.map((m) => `<div class="m ${m.role}"><div class="who">${who[m.role]}・${hhmm(m.time)}</div>${esc(m.content)}</div>`).join("");
  body.scrollTop = body.scrollHeight;
}

// ---------- 回廠提醒 ----------
async function reminders() {
  const list = await S("/api/admin/reminders");
  view.innerHTML = `<div class="card"><h2>回廠提醒</h2>
    <p class="muted small mb">車主選擇延後的項目，交車時自動排程；到期前透過 LINE／App 推播（示意，尚未實際發送）。</p>
    ${list.length ? list.map((r) => `<div class="rem">
      <div><div style="font-weight:800;font-size:18px">${r.due_date.replaceAll("-", "/")}</div>
        ${r.due_km ? `<div class="faint">或 ${r.due_km.toLocaleString()} km</div>` : ""}</div>
      <div class="row"><img class="thumb" style="width:36px;height:36px" src="${esc(r.image_url)}" alt="">
        <div><b>${esc(r.part)}</b><div class="faint">${esc(r.plate)}・${esc(r.owner_name)}</div></div></div>
      <div class="line-bubble"><div>${esc(r.message)}</div></div></div>`).join("")
      : `<div class="empty">目前沒有回廠提醒。車主選擇延後的項目，交車後會出現在這裡。</div>`}</div>`;
}

// ---------- 零件與規則 ----------
const RULE_ZH = { measure: "量測門檻", mileage: "里程／時間", inspect: "技師判定" };

async function parts() {
  const list = await S("/api/admin/parts");
  const num = (p, f, step = 1) => `<input class="input" type="number" step="${step}" data-f="${f}" value="${p[f] ?? ""}" style="width:86px">`;
  view.innerHTML = `<div class="card"><h2>零件與規則</h2>
    <p class="muted small mb">門檻、間隔與價格皆為示意。修改後按該列「儲存」，下一張工單就會套用。</p>
    <div style="overflow-x:auto"><table class="tbl"><thead><tr><th>料號</th><th>零件</th><th>規則</th>
      <th>安全門檻</th><th>預警值</th><th>間隔 km</th><th>間隔 月</th><th>預警 km</th><th>延後複查 月</th>
      <th>零件 NT$</th><th>工資 NT$</th><th>工時 分</th><th>安全關鍵</th><th></th></tr></thead><tbody>
    ${list.map((p) => `<tr><td class="faint">${esc(p.part_no)}</td>
      <td><input class="input" data-f="name_zh" value="${esc(p.name_zh)}" style="width:160px"></td>
      <td><span class="badge gray">${RULE_ZH[p.rule_type]}</span></td>
      <td>${p.rule_type === "measure" ? num(p, "safe_min", 0.1) + `<span class="faint"> ${esc(p.unit)}</span>` : "—"}</td>
      <td>${p.rule_type === "measure" ? num(p, "warn_min", 0.1) : "—"}</td>
      <td>${p.rule_type === "mileage" ? num(p, "interval_km", 1000) : "—"}</td>
      <td>${p.rule_type === "mileage" ? num(p, "interval_months") : "—"}</td>
      <td>${p.rule_type === "mileage" ? num(p, "warn_km", 500) : "—"}</td>
      <td>${p.rule_type !== "mileage" ? num(p, "defer_months") : "—"}</td>
      <td>${num(p, "part_price", 50)}</td><td>${num(p, "labor_price", 50)}</td><td>${num(p, "labor_minutes", 5)}</td>
      <td><input type="checkbox" data-f="safety_critical" ${p.safety_critical ? "checked" : ""}></td>
      <td><button class="btn sm" data-save="${p.id}">儲存</button></td></tr>`).join("")}
    </tbody></table></div></div>`;
  view.querySelectorAll("[data-save]").forEach((b) => (b.onclick = async () => {
    const body = {};
    b.closest("tr").querySelectorAll("[data-f]").forEach((inp) => {
      const f = inp.dataset.f;
      if (inp.type === "checkbox") body[f] = inp.checked;
      else if (inp.type === "number") body[f] = inp.value === "" ? null : Number(inp.value);
      else body[f] = inp.value;
    });
    try { await P(`/api/admin/parts/${b.dataset.save}`, body, "PUT"); toast("已儲存", "ok"); }
    catch (err) { toast(err.message, "err"); }
  }));
}

// ---------- 示範工具 ----------
function demo() {
  const base = state.info?.public_base_url || "";
  view.innerHTML = `<div class="grid2">
    <div class="card"><h2>三個端的網址</h2>
      <p class="mt">管理平台：<a href="/a/" target="_blank">${esc(base)}/a/</a></p>
      <p class="mt-s">技師端：<a href="/t/" target="_blank">${esc(base)}/t/</a></p>
      <p class="mt-s">車主端：由接待建單產生的專屬 QR 進入</p>
      <p class="faint mt">流程：接待建單 → 車主掃 QR 確認車牌 → 技師檢查送出 → 車主決定 → 技師施工 → 交車摘要與回廠提醒。</p></div>
    <div class="card"><h2>AI 服務專員</h2>
      <p class="mt">${state.info?.llm_configured ? `已連接 Gemini（${esc(state.info.llm_model)}）。連不上時會自動改用規則式回答。`
        : "尚未設定 GEMINI_API_KEY，目前使用規則式回答。到 Google AI Studio 申請 API Key，填入 .env 後重新啟動。"}</p>
      <p class="faint mt">規則版本：${esc(state.info?.rule_version || "")}</p></div>
    <div class="card"><h2>重設示範資料</h2>
      <p class="muted small">清空所有工單、對話與提醒，重建 3 台示範車（ABC-1234、BCD-5678、CDE-9012）。</p>
      <button class="btn primary mt" id="resetBtn">重設示範資料</button></div>
    <div class="card"><h2>示範情境</h2>
      <p class="small mt-s"><b>ABC-1234 王先生</b> 31,200 km：前輪胎紋 1.4 mm（必須處理）、前來令片 3.6 mm、機油逾期、雨刷建議更換</p>
      <p class="small mt-s"><b>BCD-5678 林小姐</b> 19,800 km：電瓶 60%、冷氣濾網與機油接近更換</p>
      <p class="small mt-s"><b>CDE-9012 陳先生</b> 9,950 km：只有機油接近更換，其餘「今天不用換」</p></div></div>`;
  document.getElementById("resetBtn").onclick = async () => {
    const ok = await confirmDialog("重設示範資料？", "所有工單、對話與提醒都會被清空。", "重設");
    if (!ok) return;
    await P("/api/admin/demo/reset");
    state.handoffIds.clear();
    state.activeHandoff = null;
    state.orderStatus = {};
    toast("已重設示範資料", "ok");
  };
}

// ---------- 啟動 ----------
(async () => {
  await ensureStaff();
  state.info = await S("/api/admin/info");
  document.getElementById("llmStatus").textContent = state.info.llm_configured ? `AI：${state.info.llm_model}` : "AI：規則式備援";
  go("reception");
  await Promise.all([pollHandoffs(), pollOrders()]);
  setInterval(() => { pollHandoffs().catch(() => {}); pollOrders().catch(() => {}); }, 3000);
})();
