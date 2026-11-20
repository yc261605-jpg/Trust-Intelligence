// 三個前端共用的小工具：呼叫 API、跳出提示、格式化
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const money = (n) => "NT$" + Number(n || 0).toLocaleString("zh-TW");
const hhmm = (iso) => (iso ? iso.slice(11, 16) : "—");
const mdhm = (iso) => (iso ? `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))} ${iso.slice(11, 16)}` : "—");

const LEVEL = {
  immediate: { zh: "立即處理", cls: "immediate" },
  deferrable: { zh: "可延後", cls: "deferrable" },
  normal: { zh: "目前正常", cls: "normal" },
};
const STATUS_STEPS = ["已建立", "檢查中", "待車主確認", "已確認", "施工中", "已完工"];

async function api(method, url, body, opts = {}) {
  const headers = {};
  if (opts.staff) headers["X-Staff-Key"] = localStorage.getItem("staffKey") || "";
  if (opts.customer) headers["Authorization"] = "Bearer " + (sessionStorage.getItem("custToken") || "");
  let payload;
  if (opts.form) {
    payload = opts.form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(url, { method, headers, body: payload });
  if (opts.raw) {
    if (!res.ok) throw new Error("讀取失敗");
    return res;
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* 空回應 */ }
  if (!res.ok) {
    const err = new Error((data && (typeof data.detail === "string" ? data.detail : "資料格式錯誤")) || `錯誤 ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, type = "") {
  let box = document.getElementById("toasts");
  if (!box) {
    box = document.createElement("div");
    box.id = "toasts";
    document.body.appendChild(box);
  }
  // 同樣訊息不重複疊加，最多同時顯示 2 則
  [...box.children].forEach((x) => { if (x.textContent === msg) x.remove(); });
  while (box.children.length >= 2) box.firstChild.remove();
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), type === "err" ? 5000 : 3500);
}

function confirmDialog(title, html, okText = "確認", okClass = "primary") {
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `<div class="modal"><h3>${esc(title)}</h3><div class="muted">${html}</div>
      <div class="actions"><button class="btn" data-x="0">取消</button>
      <button class="btn ${okClass}" data-x="1">${esc(okText)}</button></div></div>`;
    bg.addEventListener("click", (e) => {
      const x = e.target.dataset.x;
      if (x !== undefined || e.target === bg) { bg.remove(); resolve(x === "1"); }
    });
    document.body.appendChild(bg);
  });
}

function lightbox(src) {
  const bg = document.createElement("div");
  bg.className = "lightbox";
  bg.innerHTML = `<img src="${esc(src)}" alt="檢查照片">`;
  bg.onclick = () => bg.remove();
  document.body.appendChild(bg);
}

// 員工密碼（技師端、管理平台共用）
async function ensureStaff() {
  if (localStorage.getItem("staffKey")) {
    try { await api("GET", "/api/admin/info", undefined, { staff: true }); return; } catch (e) { /* 密碼失效 */ }
  }
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `<form class="modal"><h3>員工登入</h3>
      <p class="muted small mb">請輸入員工密碼（.env 的 STAFF_PASSWORD，預設 toyota-demo）</p>
      <input class="input" type="password" name="pw" autofocus placeholder="員工密碼">
      <div class="actions"><button class="btn primary" type="submit">登入</button></div></form>`;
    bg.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      localStorage.setItem("staffKey", e.target.pw.value);
      try {
        await api("GET", "/api/admin/info", undefined, { staff: true });
        bg.remove();
        resolve();
      } catch (err) {
        toast("密碼錯誤", "err");
      }
    };
    document.body.appendChild(bg);
  });
}

function stepsHtml(step) {
  return `<div class="steps">${STATUS_STEPS.map((s, i) =>
    `<div class="s ${i < step ? "done" : i === step ? "now" : ""}"><div class="bar"></div>${s}</div>`).join("")}</div>`;
}

const GAUGE_LABEL = { mm: "厚度／深度", "%": "健康度" };

function gaugeHtml(it) {
  if (it.rule_type !== "measure" || it.measured_value == null) return "";
  const max = Math.max(it.warn_min * 2.2, it.measured_value * 1.2);
  const pct = (v) => Math.min(100, Math.max(0, (v / max) * 100)).toFixed(1) + "%";
  const v = it.measured_value;
  const color = v < it.safe_min ? "var(--red)" : v < it.warn_min ? "var(--amber)" : "var(--green)";
  const label = it.name.includes("胎") ? "胎紋深度" : it.name.includes("來令") ? "來令片厚度" : (GAUGE_LABEL[it.unit] || "量測值");
  return `<div class="gauge" style="--safe:${pct(it.safe_min)};--warn:${pct(it.warn_min)}">
    <div class="head"><span class="faint">${esc(label)}</span>
      <span><span class="val" style="color:${color}">${v}</span><span class="faint"> ${esc(it.unit)}／門檻 ${it.safe_min} ${esc(it.unit)}</span></span></div>
    <div class="track"><div class="pin" style="left:${pct(v)};background:${color}"></div></div>
    <div class="labels"><span style="left:0;transform:none">0</span><span style="left:${pct(it.safe_min)}">${it.safe_min}</span>
      <span style="left:${pct(it.warn_min)}">${it.warn_min}</span><span style="right:0;transform:none">${(+max.toFixed(1))} ${esc(it.unit)}</span></div></div>`;
}

function photosHtml(photos) {
  if (!photos || !photos.length) return "";
  return `<div class="photos">${photos.map((p) =>
    `<img src="${esc(p)}" alt="技師檢查照片" onclick="lightbox('${esc(p)}')">`).join("")}</div>`;
}

// 品牌標誌：把官方 TOYOTA 標誌檔放在 /static/img/toyota-logo.svg（或 .png）就會自動顯示；沒有檔案時只顯示文字
let LOGO_SRC = null;
(function probeLogo(list) {
  if (!list.length) return;
  const img = new Image();
  img.onload = () => {
    LOGO_SRC = list[0];
    document.querySelectorAll(".brandmark").forEach((el) => {
      if (!el.querySelector("img")) el.insertAdjacentHTML("afterbegin", `<img src="${LOGO_SRC}" alt="TOYOTA">`);
    });
  };
  img.onerror = () => probeLogo(list.slice(1));
  img.src = list[0];
})(["/static/img/toyota-logo.svg", "/static/img/toyota-logo.png"]);

function brandHtml(sub = "") {
  return `<span class="brandmark">${LOGO_SRC ? `<img src="${LOGO_SRC}" alt="TOYOTA">` : ""}
    <span class="wm">Trust <b>Intelligence</b>${sub ? `<span class="bsub">${sub}</span>` : ""}</span></span>`;
}

const FOOTER = `<div class="footer">競賽概念原型｜非 TOYOTA 官方產品或介面｜價格、門檻與規格皆為示意｜影像為 AI 生成</div>`;

// ---------- 果凍互動與動畫 ----------
// 按下按鈕彈一下
document.addEventListener("pointerdown", (e) => {
  const el = e.target.closest(".btn, .seg button, .tab, .chips button, .pick button, .icard .top");
  if (!el || el.disabled) return;
  el.classList.remove("boing");
  void el.offsetWidth;            // 重新觸發動畫
  el.classList.add("boing");
  el.addEventListener("animationend", () => el.classList.remove("boing"), { once: true });
});

// 子元素依序進場：container 加上 anim（或 slide-in）class
function stagger(container, cls = "anim") {
  if (!container) return;
  container.classList.remove("anim", "slide-in");
  [...container.children].forEach((c, i) => c.style.setProperty("--i", Math.min(i, 10)));
  void container.offsetWidth;
  container.classList.add(cls);
}

// 金額跳動
function countUp(el, to, fmt = money, ms = 600) {
  if (!el) return;
  const from = Number(el.dataset.v || 0);
  el.dataset.v = to;
  if (from === to || matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms);
    const e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(Math.round(from + (to - from) * e));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// 同一個位置只在內容換頁時播一次進場（輪詢重畫不重播）
const _viewKeys = {};
function enterOnce(el, slot, key, cls = "anim") {
  if (!el || _viewKeys[slot] === key) return;
  _viewKeys[slot] = key;
  stagger(el, cls);
}
