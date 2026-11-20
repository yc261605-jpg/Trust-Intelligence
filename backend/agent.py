"""車主端 Agent。

流程：車主提問 → Gemini（OpenAI 相容 API）判斷意圖並呼叫白名單工具
      → 依工具結果改寫成白話 → Answer Verifier 檢查 → 回覆
- 工具只能查「這張工單」的資料；分級結論以規則引擎為準，LLM 不能改。
- 沒設定 GEMINI_API_KEY 或連不上時，改用規則式備援回答，Demo 不會中斷。
- 另外提供 make_brief()：技師送出後，產生給服務專員的 30 秒口頭說明稿。
"""
import json
import re
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .history import find_last_replacement
from .models import ChatMessage, InspectionItem, Level, WorkOrder, WorkOrderStatus
from .rules import LEVEL_ZH
from .services import STATUS_ZH, compute_eta, order_view

MAX_TOOL_ROUNDS = 4
UNKNOWN_MARK = "這個問題我沒有足夠的資料回答"


@dataclass
class AgentReply:
    text: str
    sources: list[str] = field(default_factory=list)
    suggest_handoff: bool = False
    engine: str = "fallback"   # llm | fallback


SYSTEM_PROMPT = """你是 TOYOTA 保養廠的「AI 服務專員」，在車主等待時回答本次保養的問題。

規則（務必遵守）：
1. 一律使用繁體中文、台灣用語，口氣親切、句子簡短，回答控制在 120 字內。
2. 只能根據工具查到的資料回答。查不到就說「這個問題我沒有足夠的資料回答」，並建議轉接服務專員。
3. 項目的分級（立即處理／可延後／目前正常）由原廠規則決定，你不能改變或質疑。
4. 「立即處理」的項目已低於安全門檻，絕對不可以建議延後或說不用換；車主想延後時，請建議轉接服務專員當面說明。
5. 不可自行推估價格、零件壽命或維修時間，只能引用工具給的數字。
6. 回答時附上依據，例如技師量測值、門檻、剩餘公里或規則版本。
7. 不要討論與本次保養無關的話題，也不要透露其他車主的資料。"""


TOOLS = [
    {"type": "function", "function": {
        "name": "get_work_order_summary",
        "description": "取得本次工單摘要：車型、公里數、狀態、每個項目的分級與價格、合計金額、預估完成時間"}},
    {"type": "function", "function": {
        "name": "get_item_detail",
        "description": "取得單一檢查項目的細節：量測值、門檻、技師原因、分級依據、延後影響、白話說明、價格",
        "parameters": {"type": "object", "properties": {
            "part_name": {"type": "string", "description": "零件名稱或關鍵字，例如：前輪胎、煞車、電瓶、機油"}},
            "required": ["part_name"]}}},
    {"type": "function", "function": {
        "name": "get_service_history",
        "description": "查某個零件上次更換的日期與公里數",
        "parameters": {"type": "object", "properties": {
            "part_name": {"type": "string"}}, "required": ["part_name"]}}},
    {"type": "function", "function": {
        "name": "get_progress",
        "description": "取得目前施工進度、已完成項目與預估完成時間"}},
]

# 車主常用的說法 → 料號
ALIASES = {
    "TI-P001": ["機油"],
    "TI-P002": ["機油芯", "機油濾芯"],
    "TI-P003": ["空氣濾網", "空濾", "引擎濾網"],
    "TI-P004": ["冷氣濾網", "冷氣", "空調濾網"],
    "TI-P005": ["前輪煞車", "前煞車", "前來令", "煞車來令", "來令片", "煞車皮", "煞車"],
    "TI-P006": ["後輪煞車", "後煞車", "後來令"],
    "TI-P007": ["前輪胎", "前胎", "胎紋", "輪胎", "胎"],
    "TI-P008": ["後輪胎", "後胎"],
    "TI-P009": ["電瓶", "電池", "12v"],
    "TI-P010": ["煞車油"],
    "TI-P011": ["雨刷"],
    "TI-P012": ["油電電池", "進風濾網", "電池濾網"],
    "TI-P013": ["變頻器", "冷卻液"],
    "TI-P014": ["差速器", "齒輪油", "e-four"],
}


# ---------- 工具 ----------

def find_items(wo: WorkOrder, text: str) -> list[InspectionItem]:
    """依車主文字找出提到的項目。較長的關鍵字優先（「煞車油」不會被當成「煞車」）。"""
    text = text.lower()
    scored = []
    for item in wo.items:
        keys = ALIASES.get(item.part.part_no, []) + [re.sub(r"（.*?）", "", item.part.name_zh)]
        best = max((len(k) for k in keys if k.lower() in text), default=0)
        if best:
            scored.append((best, item))
    if not scored:
        return []
    top = max(s for s, _ in scored)
    matched = [i for s, i in scored if s == top]
    # 同一個關鍵字對到多項時（例如「輪胎」），把需要注意的排前面
    order = {Level.IMMEDIATE: 0, Level.DEFERRABLE: 1, Level.NORMAL: 2, None: 3}
    return sorted(matched, key=lambda i: order.get(i.level, 3))


def _item_detail(db: Session, wo: WorkOrder, item: InspectionItem) -> dict:
    p = item.part
    detail = {
        "零件": p.name_zh, "分級": LEVEL_ZH.get(item.level, "尚未檢查"), "判斷依據": item.basis,
        "技師原因": item.reason, "白話說明": p.explain_text, "延後影響": p.defer_impact_text,
        "價格": {"零件": p.part_price, "工資": p.labor_price, "合計": p.part_price + p.labor_price},
        "標準工時分鐘": p.labor_minutes, "安全關鍵": p.safety_critical,
        "車主選擇": {"today": "今天處理", "defer": "延後"}.get(item.customer_choice),
    }
    if item.measured_value is not None:
        detail["量測值"] = f"{item.measured_value:g} {p.unit or ''}".strip()
        detail["安全門檻"] = f"{p.safe_min:g} {p.unit or ''}".strip()
        detail["預警值"] = f"{p.warn_min:g} {p.unit or ''}".strip()
    if item.remaining_km is not None:
        detail["剩餘公里"] = item.remaining_km
    if item.photos:
        detail["照片"] = f"技師拍了 {len(item.photos)} 張照片，可在決策卡查看"
    return detail


def run_tool(db: Session, wo: WorkOrder, name: str, args: dict) -> dict:
    checked = wo.status not in (WorkOrderStatus.CREATED, WorkOrderStatus.INSPECTING)
    if name == "get_work_order_summary":
        view = order_view(wo)
        return {
            "車型": view["vehicle"]["model"], "車牌": view["vehicle"]["plate"],
            "公里數": wo.current_km, "工單狀態": STATUS_ZH[wo.status], "規則版本": wo.rule_version,
            "項目": [{"零件": i["name"], "分級": i["level_zh"], "依據": i["basis"], "價格": i["price"]}
                   for i in view["items"]] if checked else "技師還在檢查，尚未產生結果",
            "今天處理合計金額": view["today_total"],
            "預估完成時間": view["eta"],
        }
    if name == "get_service_history" and not wo.items:
        return {"結果": "技師尚未開始檢查，請稍後再問"}
    if name in ("get_item_detail", "get_service_history"):
        if not checked and name == "get_item_detail":
            return {"結果": "技師還在檢查，尚未產生結果"}
        items = find_items(wo, args.get("part_name", ""))
        if not items:
            return {"結果": "本次工單沒有這個項目", "可查詢的項目": [i.part.name_zh for i in wo.items]}
        if name == "get_item_detail":
            return {"項目": [_item_detail(db, wo, i) for i in items[:2]]}
        out = []
        for i in items[:2]:
            km, day = find_last_replacement(db, wo.vehicle, i.part)
            out.append({"零件": i.part.name_zh,
                        "上次更換": "交車時的原廠零件" if km == 0 else f"{day.isoformat()}，{km:,} km"})
        return {"紀錄": out}
    if name == "get_progress":
        today = [i for i in wo.items if i.customer_choice == "today"]
        return {
            "工單狀態": STATUS_ZH[wo.status],
            "已完成": [i.part.name_zh for i in today if i.work_status == "done"],
            "施工中": [i.part.name_zh for i in today if i.work_status == "in_progress"],
            "待施工": [i.part.name_zh for i in today if i.work_status == "pending"],
            "預估完成時間": wo.eta.strftime("%H:%M") if wo.eta else "車主確認後才會計算",
        }
    return {"錯誤": f"沒有這個工具：{name}"}


# ---------- 對外入口 ----------

HANDOFF_WORDS = ["真人", "專員", "客服", "人工", "找人", "店員"]
UNHAPPY_WORDS = ["生氣", "不爽", "爛", "騙", "坑", "太貴", "不滿", "投訴", "客訴", "亂報"]


def answer(db: Session, wo: WorkOrder, question: str) -> AgentReply:
    wants_human = any(w in question for w in HANDOFF_WORDS)
    unhappy = any(w in question for w in UNHAPPY_WORDS)

    reply = None
    if _llm_enabled():
        try:
            reply = _llm_answer(db, wo, question)
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            reply = None  # 連不上或格式不對 → 備援
    if reply is None:
        reply = _fallback_answer(db, wo, question)

    reply.text = verify(reply.text, wo)
    if wants_human or unhappy or _recent_unknown_count(db, wo) >= 1 and UNKNOWN_MARK in reply.text:
        reply.suggest_handoff = True
    if wants_human:
        reply.text = "沒問題，按下方「轉接真人」，服務專員會直接在這裡回覆你。"
    return reply


def _recent_unknown_count(db: Session, wo: WorkOrder) -> int:
    last = (db.query(ChatMessage).filter_by(work_order_id=wo.id, role="agent")
            .order_by(ChatMessage.id.desc()).limit(1).all())
    return sum(1 for m in last if UNKNOWN_MARK in m.content)


# ---------- Answer Verifier ----------

FORBIDDEN_FOR_IMMEDIATE = ["可以延後", "可延後", "先不用", "不用換", "不需要換", "不必換", "晚點再換",
                           "下次再換", "還可以開", "沒關係"]


def verify(text: str, wo: WorkOrder) -> str:
    """立即處理的項目若出現「可以延後」之類字眼，整段改成固定的安全回覆。"""
    sentences = re.split(r"[。！？!?\n]", text)
    for item in wo.items:
        if item.level != Level.IMMEDIATE:
            continue
        keys = ALIASES.get(item.part.part_no, [])[:2] + [re.sub(r"（.*?）", "", item.part.name_zh)]
        for s in sentences:
            if any(k in s for k in keys) and any(f in s for f in FORBIDDEN_FOR_IMMEDIATE):
                return (f"{item.part.name_zh}：{item.basis}。這是安全關鍵項目，系統不提供延後；"
                        f"如果想進一步了解，可以按「轉接真人」請服務專員當面說明。")
    return text


# ---------- LLM（Gemini） ----------

def _llm_enabled() -> bool:
    return bool(settings.gemini_api_key)


def _chat(client: httpx.Client, messages: list[dict], tools: list | None = None, max_tokens: int = 500) -> dict:
    body = {"model": settings.gemini_model, "messages": messages,
            "temperature": 0.3, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    resp = client.post(f"{settings.gemini_base_url}/chat/completions",
                       headers={"Authorization": f"Bearer {settings.gemini_api_key}"}, json=body)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def _history(db: Session, wo: WorkOrder, limit: int = 6) -> list[dict]:
    rows = (db.query(ChatMessage).filter(ChatMessage.work_order_id == wo.id,
                                         ChatMessage.role.in_(["customer", "agent"]))
            .order_by(ChatMessage.id.desc()).limit(limit + 1).all())
    rows = list(reversed(rows))[:-1]  # 最後一筆是剛剛存的提問，等一下另外加
    return [{"role": "user" if m.role == "customer" else "assistant", "content": m.content} for m in rows]


def _llm_answer(db: Session, wo: WorkOrder, question: str) -> AgentReply:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *_history(db, wo),
                {"role": "user", "content": question}]
    used = []
    with httpx.Client(timeout=settings.llm_timeout) as client:
        for _ in range(MAX_TOOL_ROUNDS):
            msg = _chat(client, messages, TOOLS)
            calls = msg.get("tool_calls") or []
            if not calls:
                text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
                if not text:
                    raise ValueError("LLM 回覆空白")
                return AgentReply(text=text, sources=_sources(wo, used), engine="llm")
            # 原樣回傳 tool_calls（Gemini 3 會附 thought signature，必須一起送回）
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call["function"]["name"]
                raw = call["function"].get("arguments") or "{}"
                args = json.loads(raw) if isinstance(raw, str) else raw
                used.append((fn, args))
                result = run_tool(db, wo, fn, args)
                messages.append({"role": "tool", "tool_call_id": call.get("id", fn),
                                 "name": fn, "content": json.dumps(result, ensure_ascii=False)})
    raise ValueError("工具呼叫次數過多")


def _sources(wo: WorkOrder, used: list[tuple[str, dict]]) -> list[str]:
    src = []
    for fn, args in used:
        if fn in ("get_item_detail",):
            for i in find_items(wo, args.get("part_name", ""))[:2]:
                if i.measured_value is not None:
                    src.append(f"技師量測：{i.part.name_zh} {i.measured_value:g} {i.part.unit or ''}".strip())
                src.append(f"原廠規則 {wo.rule_version or ''}：{i.part.name_zh}".strip())
        elif fn == "get_service_history":
            src.append("保養紀錄")
        elif fn == "get_progress":
            src.append("工單進度")
        elif fn == "get_work_order_summary":
            src.append("本次工單")
    return list(dict.fromkeys(src))


# ---------- 備援：規則式回答 ----------

def _price(item: InspectionItem) -> str:
    p = item.part
    return f"NT${p.part_price + p.labor_price:,}（零件 {p.part_price:,}＋工資 {p.labor_price:,}）"


def _fallback_answer(db: Session, wo: WorkOrder, q: str) -> AgentReply:
    src = [f"本次工單（規則版本 {wo.rule_version}）"] if wo.rule_version else ["本次工單"]

    if wo.status in (WorkOrderStatus.CREATED, WorkOrderStatus.INSPECTING):
        return _waiting_answer(db, wo, q, src)

    items = find_items(wo, q)
    item = items[0] if items else None

    if any(k in q for k in ["多久", "進度", "好了沒", "什麼時候", "幾點", "等多久", "完成時間"]):
        if wo.status == WorkOrderStatus.AWAITING_CUSTOMER:
            return AgentReply("目前在等你確認決策卡，確認送出後技師就會開始施工，並算出預估完成時間。", src)
        if wo.status == WorkOrderStatus.COMPLETED:
            return AgentReply("保養已經全部完成，可以交車了！交車摘要在進度頁下方。", src)
        eta = (wo.eta or compute_eta(wo)).strftime("%H:%M")
        done = [i.part.name_zh for i in wo.items if i.work_status == "done" and i.customer_choice == "today"]
        doing = [i.part.name_zh for i in wo.items if i.work_status == "in_progress"]
        parts = []
        if done:
            parts.append(f"已完成 {'、'.join(done)}")
        if doing:
            parts.append(f"正在處理 {'、'.join(doing)}")
        status = "，".join(parts) or "技師即將開始施工"
        return AgentReply(f"{status}，預估 {eta} 完成。", ["工單進度"])

    if item and item.remaining_km is not None and any(k in q for k in ["剩", "公里", "還能開", "還可以開"]):
        if item.remaining_km > 0:
            text = f"{item.part.name_zh}距建議更換還有約 {item.remaining_km:,} km（{LEVEL_ZH.get(item.level)}）。"
        else:
            text = f"{item.part.name_zh}已超過建議更換里程 {abs(item.remaining_km):,} km（{LEVEL_ZH.get(item.level)}）。"
        return AgentReply(text, src)

    if any(k in q for k in ["多少錢", "費用", "價格", "價錢", "報價", "總共", "多少"]):
        if item:
            return AgentReply(f"{item.part.name_zh}費用 {_price(item)}，標準工時約 {item.part.labor_minutes} 分鐘。",
                              src + ["原廠價目（示意）"])
        needed = [i for i in wo.items if i.level in (Level.IMMEDIATE, Level.DEFERRABLE)]
        lines = "、".join(f"{i.part.name_zh} NT${i.part.part_price + i.part.labor_price:,}" for i in needed)
        must = sum(i.part.part_price + i.part.labor_price for i in needed if i.level == Level.IMMEDIATE)
        return AgentReply(f"本次建議處理的項目：{lines}。其中必須今天處理的合計 NT${must:,}，"
                          f"其餘可以自己決定今天換或延後。", src)

    if item is None:
        if any(k in q for k in ["要換", "需要", "建議", "哪些", "要不要", "有問題"]):
            return AgentReply(_overview(wo), src)
        return AgentReply(f"{UNKNOWN_MARK}。你可以問我某個項目為什麼要換、費用、不換會怎樣或還要等多久；"
                          f"也可以按「轉接真人」。", src)

    item_src = src + ([f"技師量測：{item.measured_value:g} {item.part.unit or ''}".strip()]
                      if item.measured_value is not None else [])

    if any(k in q for k in ["不換", "不做", "延後", "會怎樣", "晚點", "下次", "不處理", "可以不"]):
        if item.level == Level.IMMEDIATE:
            text = (f"{item.part.name_zh}{item.basis}。這是安全項目，今天必須處理，系統不提供延後；"
                    f"需要的話我幫你轉服務專員當面說明。")
        elif item.level == Level.DEFERRABLE:
            text = f"{item.part.name_zh}可以延後：{item.part.defer_impact_text}（{item.basis}）"
        else:
            text = f"{item.part.name_zh}目前正常，今天不用換。{item.basis}。"
        return AgentReply(text, item_src)

    if any(k in q for k in ["上次", "什麼時候換", "多久沒換"]):
        km, day = find_last_replacement(db, wo.vehicle, item.part)
        last = "交車時的原廠零件，還沒更換過" if km == 0 else f"上次在 {day:%Y/%m/%d}、{km:,} km 更換"
        return AgentReply(f"{item.part.name_zh}{last}。", ["保養紀錄"])

    # 預設：為什麼／說明
    level = LEVEL_ZH.get(item.level, "")
    reason = f"技師說明：{item.reason}。" if item.reason else ""
    text = f"{item.part.name_zh}判定為「{level}」：{item.basis}。{reason}{item.part.explain_text}"
    if item.level != Level.NORMAL:
        text += f"費用 {_price(item)}。"
    return AgentReply(text, item_src)


def _waiting_answer(db: Session, wo: WorkOrder, q: str, src: list[str]) -> AgentReply:
    """技師檢查中：回答檢查項目、時間、保養紀錄；結果要等檢查完成。"""
    from .services import INSPECT_MINUTES, model_parts, progress_view
    parts = model_parts(db, wo.vehicle)
    if any(k in q for k in ["哪些", "項目", "檢查什麼", "會檢查"]):
        measured = [p.name_zh for p in parts if p.rule_type != "mileage"]
        auto = [p.name_zh for p in parts if p.rule_type == "mileage"]
        return AgentReply(f"這次共檢查 {len(parts)} 項。技師現場量測拍照：{'、'.join(measured)}；"
                          f"依里程與保養紀錄自動計算：{'、'.join(auto)}。", src)
    if any(k in q for k in ["多久", "時間", "進度", "好了", "什麼時候", "幾點"]):
        p = progress_view(wo)
        done = f"目前已檢查 {p['checked']}/{p['total']} 項，" if wo.status == WorkOrderStatus.INSPECTING else ""
        return AgentReply(f"{done}整車檢查大約需要 {INSPECT_MINUTES} 分鐘。檢查完成後決策卡會自動出現在這個頁面，"
                          f"施工時間要等你決定今天換哪些項目才能算出來。", src)
    if any(k in q for k in ["上次", "紀錄", "換過", "換了什麼"]):
        from .models import ServiceHistory
        last = (db.query(ServiceHistory).filter_by(vehicle_id=wo.vehicle_id)
                .order_by(ServiceHistory.replaced_on.desc()).first())
        if last is None:
            return AgentReply(f"這是愛車第一次回廠保養，交車日是 {wo.vehicle.delivered_on:%Y/%m/%d}。", ["保養紀錄"])
        same = (db.query(ServiceHistory).filter_by(vehicle_id=wo.vehicle_id, replaced_on=last.replaced_on).all())
        names = "、".join(h.part.name_zh for h in same)
        return AgentReply(f"上次保養是 {last.replaced_on:%Y/%m/%d}、{last.replaced_km:,} km，更換了{names}。", ["保養紀錄"])
    item = (find_items(wo, q) or [None])[0] if wo.items else None
    name = item.part.name_zh if item else "各項目"
    return AgentReply(f"技師還在檢查中，{name}的結果出來後我就能說明狀況與費用。檢查完成時決策卡會自動出現。", src)


def _overview(wo: WorkOrder) -> str:
    groups = {Level.IMMEDIATE: [], Level.DEFERRABLE: [], Level.NORMAL: []}
    for i in wo.items:
        if i.level:
            groups[i.level].append(i.part.name_zh)
    parts = []
    if groups[Level.IMMEDIATE]:
        parts.append(f"必須今天處理：{'、'.join(groups[Level.IMMEDIATE])}")
    if groups[Level.DEFERRABLE]:
        parts.append(f"可以延後：{'、'.join(groups[Level.DEFERRABLE])}")
    parts.append(f"其餘 {len(groups[Level.NORMAL])} 項目前正常，今天不用換")
    return "；".join(parts) + "。"


# ---------- 專員 30 秒說明稿 ----------

BRIEF_PROMPT = """你是 TOYOTA 保養廠的資深服務顧問。請根據下面的檢查結果，寫一段給服務專員「當面對車主說」的口頭說明稿。

要求：
1. 繁體中文、台灣口語，約 120～160 字，唸出來約 30 秒。
2. 順序：先說今天必須處理的（講出量測值和原因）→ 再說可以延後、讓車主自己決定的 → 最後主動說哪些今天不用換。
3. 只能使用資料中的數字，不可自行推估；不要推銷，語氣誠懇。
4. 直接輸出說明稿本身，不要標題、不要條列。"""


def brief_facts(wo: WorkOrder) -> dict:
    groups = {Level.IMMEDIATE: [], Level.DEFERRABLE: [], Level.NORMAL: []}
    for i in wo.items:
        if i.level:
            groups[i.level].append({"零件": i.part.name_zh, "依據": i.basis, "技師說明": i.reason,
                                    "價格": i.part.part_price + i.part.labor_price})
    return {"車主": wo.vehicle.owner_name, "車型": f"{wo.vehicle.model.year} {wo.vehicle.model.name}",
            "公里數": wo.current_km, "必須今天處理": groups[Level.IMMEDIATE],
            "可延後": groups[Level.DEFERRABLE],
            "今天不用換": [x["零件"] for x in groups[Level.NORMAL]]}


def make_brief(wo: WorkOrder) -> str:
    """產生專員說明稿；Gemini 不可用時改用範本。"""
    facts = brief_facts(wo)
    if _llm_enabled():
        try:
            with httpx.Client(timeout=settings.llm_timeout) as client:
                msg = _chat(client, [{"role": "system", "content": BRIEF_PROMPT},
                                     {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
                            max_tokens=600)
            text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
            if text:
                return verify(text, wo)
        except (httpx.HTTPError, KeyError, ValueError):
            pass
    return _template_brief(facts)


def _template_brief(f: dict) -> str:
    parts = [f"{f['車主']}您好，今天幫您的愛車檢查了 {len(f['必須今天處理']) + len(f['可延後']) + len(f['今天不用換'])} 個項目。"]
    if f["必須今天處理"]:
        x = f["必須今天處理"]
        parts.append("需要今天處理的是" + "、".join(f"{re.sub(r'（.*?）', '', i['零件'])}（{i['依據']}）" for i in x)
                     + "，這是安全項目，建議今天就換好。")
    if f["可延後"]:
        parts.append("另外" + "、".join(i["零件"] for i in f["可延後"])
                     + "已經接近更換時間，可以今天一起換，也可以延後，我們會提醒您回廠。")
    if f["今天不用換"]:
        parts.append(f"其他像{'、'.join(f['今天不用換'][:3])}等 {len(f['今天不用換'])} 項都很正常，今天不用換，照片都有保留。")
    parts.append("您可以在手機上看每一項的照片和費用，有問題隨時問我。")
    return "".join(parts)
