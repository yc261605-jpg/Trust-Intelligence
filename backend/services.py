"""業務邏輯：工單狀態流轉、逐項檢查、預估完成時間、決策卡、交車摘要、回廠提醒。

API 路由只負責收參數、檢查權限，實際動作都呼叫這裡，方便測試。
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .config import settings
from .history import find_last_replacement
from .models import (
    Choice, Event, InspectionItem, Level, ModelPart, Part, Reminder, RuleType, ServiceHistory,
    Vehicle, WorkOrder, WorkOrderStatus, WorkStatus,
)
from .rules import LEVEL_ZH, evaluate
from .security import new_qr_token

QC_MINUTES = 15            # 品檢時間（示意）
INSPECT_MINUTES = 25       # 整車檢查約需時間（示意），給車主等待頁參考

STATUS_ZH = {
    WorkOrderStatus.CREATED: "已建立",
    WorkOrderStatus.INSPECTING: "檢查中",
    WorkOrderStatus.AWAITING_CUSTOMER: "待車主確認",
    WorkOrderStatus.CONFIRMED: "已確認",
    WorkOrderStatus.IN_PROGRESS: "施工中",
    WorkOrderStatus.COMPLETED: "已完工",
}
STATUS_ORDER = list(STATUS_ZH)


class FlowError(Exception):
    """流程不允許的操作（例如狀態不對）。API 會轉成 400。"""


def add_event(db: Session, wo: WorkOrder, type_: str, message: str) -> None:
    db.add(Event(work_order_id=wo.id, type=type_, message=message))


def _require_status(wo: WorkOrder, *allowed: str) -> None:
    if wo.status not in allowed:
        names = "、".join(STATUS_ZH[s] for s in allowed)
        raise FlowError(f"工單目前是「{STATUS_ZH[wo.status]}」，此操作只能在「{names}」時進行")


# ---------- 管理平台：接待建單 ----------

def create_work_order(db: Session, vehicle: Vehicle) -> WorkOrder:
    """建立工單並產生專屬 QR token。"""
    open_order = (
        db.query(WorkOrder)
        .filter(WorkOrder.vehicle_id == vehicle.id, WorkOrder.status != WorkOrderStatus.COMPLETED)
        .first()
    )
    if open_order:
        raise FlowError(f"{vehicle.plate} 已有進行中的工單 #{open_order.id}")
    wo = WorkOrder(vehicle_id=vehicle.id, qr_token=new_qr_token())
    db.add(wo)
    db.flush()
    add_event(db, wo, "status_changed", "接待完成，愛車已交給技師")
    return wo


def regenerate_qr(wo: WorkOrder) -> None:
    """重新產生 QR（舊 QR 立即失效），並解除登入鎖定。"""
    wo.qr_token = new_qr_token()
    wo.failed_logins = 0


# ---------- 技師端：逐項檢查 ----------

def model_parts(db: Session, vehicle: Vehicle) -> list[Part]:
    rows = (db.query(ModelPart).filter(ModelPart.model_id == vehicle.model_id)
            .order_by(ModelPart.sort_order).all())
    return [r.part for r in rows]


def is_tech_item(item: InspectionItem) -> bool:
    """需要技師動手檢查的項目（里程型由系統自動計算）。"""
    return item.part.rule_type != RuleType.MILEAGE


def start_inspection(db: Session, wo: WorkOrder) -> None:
    """技師開始檢查：替車型的每個零件建立檢查項目。目視判定型預設「正常」。"""
    if wo.status == WorkOrderStatus.INSPECTING:
        return
    _require_status(wo, WorkOrderStatus.CREATED)
    for part in model_parts(db, wo.vehicle):
        db.add(InspectionItem(
            work_order_id=wo.id, part_id=part.id,
            tech_status="normal" if part.rule_type == RuleType.INSPECT else None,
        ))
    wo.status = WorkOrderStatus.INSPECTING
    add_event(db, wo, "status_changed", "技師開始檢查")
    db.flush()
    db.refresh(wo)


def _apply_rule(db: Session, wo: WorkOrder, item: InspectionItem, today: date | None = None) -> None:
    last_km, last_date = find_last_replacement(db, wo.vehicle, item.part)
    r = evaluate(item.part, current_km=wo.current_km or last_km, today=today or date.today(),
                 last_km=last_km, last_date=last_date,
                 measured_value=item.measured_value, tech_status=item.tech_status)
    item.level = r.level
    item.remaining_km = r.remaining_km
    item.remaining_months = r.remaining_months
    item.basis = r.basis
    item.price = item.part.part_price + item.part.labor_price


def set_mileage(db: Session, wo: WorkOrder, current_km: int, today: date | None = None) -> None:
    """輸入公里數：里程型項目立即自動計算並視為已檢查。"""
    _require_status(wo, WorkOrderStatus.INSPECTING)
    last_max = max((find_last_replacement(db, wo.vehicle, i.part)[0] for i in wo.items), default=0)
    if current_km < last_max:
        raise FlowError(f"公里數不能小於上次保養紀錄的 {last_max:,} km")
    wo.current_km = current_km
    for item in wo.items:
        if item.part.rule_type == RuleType.MILEAGE:
            _apply_rule(db, wo, item, today)
            item.checked_at = item.checked_at or datetime.now()


def save_item(db: Session, wo: WorkOrder, item: InspectionItem, data: dict, today: date | None = None) -> None:
    """技師完成一項：存輸入、立即分級，並標記已檢查。"""
    _require_status(wo, WorkOrderStatus.INSPECTING)
    if item.work_order_id != wo.id:
        raise FlowError("檢查項目不屬於這張工單")
    for key in ("measured_value", "tech_status", "reason"):
        if key in data:
            setattr(item, key, data[key])
    if item.part.rule_type == RuleType.MEASURE and item.measured_value is None:
        raise FlowError(f"請輸入{item.part.name_zh}的量測值")
    if item.measured_value is not None and item.measured_value < 0:
        raise FlowError("量測值不能是負數")
    if item.part.rule_type == RuleType.MILEAGE and wo.current_km is None:
        raise FlowError("請先輸入公里數")
    _apply_rule(db, wo, item, today)
    item.checked_at = datetime.now()


def progress_view(wo: WorkOrder) -> dict:
    tech_items = [i for i in wo.items if is_tech_item(i)]
    return {
        "km_done": wo.current_km is not None,
        "checked": sum(1 for i in tech_items if i.checked_at),
        "total": len(tech_items),
        "auto_total": sum(1 for i in wo.items if not is_tech_item(i)),
    }


def submit_inspection(db: Session, wo: WorkOrder, today: date | None = None) -> None:
    """技師送出：全部重新跑一次規則，工單變成「待車主確認」。"""
    _require_status(wo, WorkOrderStatus.INSPECTING)
    if wo.current_km is None:
        raise FlowError("請先輸入公里數")
    missing = [i.part.name_zh for i in wo.items if is_tech_item(i) and not i.checked_at]
    if missing:
        raise FlowError("還有項目沒檢查：" + "、".join(missing))
    for item in wo.items:
        _apply_rule(db, wo, item, today)
        item.checked_at = item.checked_at or datetime.now()
    wo.rule_version = settings.rule_version
    wo.inspected_at = datetime.now()
    wo.status = WorkOrderStatus.AWAITING_CUSTOMER
    c = level_counts(wo)
    add_event(db, wo, "status_changed",
              f"技師檢查完成：必須處理 {c[Level.IMMEDIATE]} 項、可延後 {c[Level.DEFERRABLE]} 項、"
              f"今天不用換 {c[Level.NORMAL]} 項")


def level_counts(wo: WorkOrder) -> dict[str, int]:
    counts = {Level.IMMEDIATE: 0, Level.DEFERRABLE: 0, Level.NORMAL: 0}
    for i in wo.items:
        if i.level:
            counts[i.level] += 1
    return counts


# ---------- 施工 ----------

def today_items(wo: WorkOrder) -> list[InspectionItem]:
    return [i for i in wo.items if i.customer_choice == Choice.TODAY]


def compute_eta(wo: WorkOrder, now: datetime | None = None) -> datetime:
    """預估完成時間 = 現在 + 尚未完成項目的標準工時 + 品檢時間。"""
    now = now or datetime.now()
    minutes = 0
    for item in today_items(wo):
        labor = item.part.labor_minutes
        if item.work_status == WorkStatus.PENDING:
            minutes += labor
        elif item.work_status == WorkStatus.IN_PROGRESS:
            elapsed = (now - item.started_at).total_seconds() / 60 if item.started_at else 0
            minutes += max(labor - elapsed, 5)
    return now + timedelta(minutes=round(minutes) + QC_MINUTES)


def start_item(db: Session, wo: WorkOrder, item: InspectionItem) -> None:
    _require_status(wo, WorkOrderStatus.CONFIRMED, WorkOrderStatus.IN_PROGRESS)
    if item.customer_choice != Choice.TODAY:
        raise FlowError("車主沒有選擇今天處理這個項目")
    if item.work_status != WorkStatus.PENDING:
        raise FlowError("這個項目已經開始或完成")
    item.work_status = WorkStatus.IN_PROGRESS
    item.started_at = datetime.now()
    if wo.status == WorkOrderStatus.CONFIRMED:
        wo.status = WorkOrderStatus.IN_PROGRESS
        add_event(db, wo, "status_changed", "開始施工")
    add_event(db, wo, "item_started", f"開始更換：{item.part.name_zh}")
    wo.eta = compute_eta(wo)


def finish_item(db: Session, wo: WorkOrder, item: InspectionItem) -> None:
    _require_status(wo, WorkOrderStatus.IN_PROGRESS)
    if item.work_status != WorkStatus.IN_PROGRESS:
        raise FlowError("這個項目還沒開始")
    item.work_status = WorkStatus.DONE
    item.done_at = datetime.now()
    add_event(db, wo, "item_done", f"完成：{item.part.name_zh}")
    wo.eta = compute_eta(wo)


def complete_order(db: Session, wo: WorkOrder) -> None:
    """品檢完成、交車：寫入保養紀錄，並為延後項目建立回廠提醒。"""
    _require_status(wo, WorkOrderStatus.CONFIRMED, WorkOrderStatus.IN_PROGRESS)
    unfinished = [i.part.name_zh for i in today_items(wo) if i.work_status != WorkStatus.DONE]
    if unfinished:
        raise FlowError("還有項目未完成：" + "、".join(unfinished))
    wo.status = WorkOrderStatus.COMPLETED
    wo.completed_at = datetime.now()
    wo.eta = wo.completed_at
    for item in today_items(wo):
        db.add(ServiceHistory(vehicle_id=wo.vehicle_id, part_id=item.part_id,
                              replaced_on=date.today(), replaced_km=wo.current_km))
    for item in wo.items:
        if item.customer_choice == Choice.DEFER:
            db.add(build_reminder(wo, item))
    add_event(db, wo, "status_changed", "品檢完成，可以交車了")


# ---------- 回廠提醒 ----------

def daily_km(wo: WorkOrder, today: date | None = None) -> float:
    """依交車至今的里程估算每天開多少公里（至少 20 km）。"""
    today = today or date.today()
    days = max((today - wo.vehicle.delivered_on).days, 30)
    return max((wo.current_km or 0) / days, 20)


def build_reminder(wo: WorkOrder, item: InspectionItem, today: date | None = None) -> Reminder:
    today = today or date.today()
    part = item.part
    due_km = None
    if part.rule_type == RuleType.MILEAGE and item.remaining_km is not None and item.remaining_km <= 0:
        days = 14                       # 已超過建議里程：兩週內回廠
        action = "更換（已超過建議里程）"
    elif part.rule_type == RuleType.MILEAGE and item.remaining_km is not None:
        due_km = (wo.current_km or 0) + item.remaining_km
        days = max(round(item.remaining_km / daily_km(wo, today)), 14)
        action = "更換"
    else:
        days = part.defer_months * 30
        action = "複查"
    due = today + timedelta(days=days)
    v = wo.vehicle
    km_text = f"或里程達 {due_km:,} km 時" if due_km else ""
    message = (f"【回廠提醒】{v.owner_name}您好，您的愛車 {v.plate} 上次保養時選擇延後的「{part.name_zh}」，"
               f"建議在 {due:%Y/%m/%d} 前{km_text}回廠{action}。回覆「預約」即可安排時段。")
    return Reminder(work_order_id=wo.id, vehicle_id=wo.vehicle_id, part_id=part.id,
                    due_date=due, due_km=due_km, message=message)


def reminder_view(r: Reminder) -> dict:
    return {"id": r.id, "part": r.part.name_zh, "image_url": r.part.image_url, "plate": r.vehicle.plate,
            "owner_name": r.vehicle.owner_name, "due_date": r.due_date.isoformat(), "due_km": r.due_km,
            "message": r.message, "status": r.status}


# ---------- 車主端：決策 ----------

def apply_decision(db: Session, wo: WorkOrder, choices: dict[int, str]) -> None:
    """車主逐項選擇。必須處理的只能今天換；可延後要選今天或延後；正常項目不用選。"""
    _require_status(wo, WorkOrderStatus.AWAITING_CUSTOMER)
    for item in wo.items:
        choice = choices.get(item.id)
        if item.level == Level.IMMEDIATE:
            if choice != Choice.TODAY:
                raise FlowError(f"{item.part.name_zh}低於安全門檻，只能今天處理；有疑問請轉接服務專員")
            item.customer_choice = Choice.TODAY
        elif item.level == Level.DEFERRABLE:
            if choice not in (Choice.TODAY, Choice.DEFER):
                raise FlowError(f"請選擇{item.part.name_zh}要今天換還是延後")
            item.customer_choice = choice
        else:
            item.customer_choice = None
    now = datetime.now()
    wo.confirmed_at = now
    wo.status = WorkOrderStatus.CONFIRMED
    wo.eta = compute_eta(wo, now)
    n_today = len(today_items(wo))
    n_defer = sum(1 for i in wo.items if i.customer_choice == Choice.DEFER)
    add_event(db, wo, "status_changed", f"車主已確認：今天處理 {n_today} 項、延後 {n_defer} 項")


# ---------- 資料整理（給前端與 Agent） ----------

def item_view(item: InspectionItem, last: tuple[int, date] | None = None) -> dict:
    p = item.part
    view = {
        "id": item.id, "part_no": p.part_no, "name": p.name_zh, "category": p.category,
        "image_url": p.image_url, "rule_type": p.rule_type, "unit": p.unit,
        "safe_min": p.safe_min, "warn_min": p.warn_min, "interval_km": p.interval_km,
        "safety_critical": p.safety_critical,
        "measured_value": item.measured_value, "tech_status": item.tech_status, "reason": item.reason,
        "checked": item.checked_at is not None,
        "level": item.level, "level_zh": LEVEL_ZH.get(item.level), "basis": item.basis,
        "remaining_km": item.remaining_km, "remaining_months": item.remaining_months,
        "price": item.price if item.price is not None else p.part_price + p.labor_price,
        "part_price": p.part_price, "labor_price": p.labor_price, "labor_minutes": p.labor_minutes,
        "explain_text": p.explain_text, "defer_impact_text": p.defer_impact_text,
        "customer_choice": item.customer_choice, "work_status": item.work_status,
        "photos": [f"/uploads/{ph.file_path}" for ph in item.photos],
    }
    if last:
        view["last_km"], view["last_date"] = last[0], last[1].isoformat()
    return view


def vehicle_view(v: Vehicle) -> dict:
    return {"plate": v.plate, "owner_name": v.owner_name, "model": f"{v.model.year} {v.model.name}",
            "powertrain": v.model.powertrain, "drivetrain": v.model.drivetrain,
            "image_url": v.model.image_url, "delivered_on": v.delivered_on.isoformat()}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="minutes") if dt else None


def order_view(wo: WorkOrder, *, include_items: bool = True) -> dict:
    data = {
        "id": wo.id, "status": wo.status, "status_zh": STATUS_ZH[wo.status],
        "status_step": STATUS_ORDER.index(wo.status), "current_km": wo.current_km,
        "rule_version": wo.rule_version, "eta": _iso(wo.eta), "brief": wo.brief,
        "created_at": _iso(wo.created_at), "inspected_at": _iso(wo.inspected_at),
        "confirmed_at": _iso(wo.confirmed_at), "completed_at": _iso(wo.completed_at),
        "vehicle": vehicle_view(wo.vehicle),
        "progress": progress_view(wo),
    }
    if include_items:
        items = [item_view(i) for i in wo.items]
        data["items"] = items
        data["counts"] = level_counts(wo)
        data["today_total"] = sum(i["price"] for i in items if i["customer_choice"] == Choice.TODAY)
    return data


def waiting_view(db: Session, wo: WorkOrder) -> dict:
    """車主等待頁：檢查進度（不含結果）＋保養紀錄。"""
    history = (db.query(ServiceHistory).filter_by(vehicle_id=wo.vehicle_id)
               .order_by(ServiceHistory.replaced_on.desc()).all())
    visits: dict[str, dict] = {}
    for h in history:
        key = h.replaced_on.isoformat()
        visits.setdefault(key, {"date": key, "km": h.replaced_km, "parts": []})["parts"].append(h.part.name_zh)
    started = next((e.created_at for e in wo.events if e.message == "技師開始檢查"), None)
    items = wo.items or []
    if items:
        checklist = [{"name": i.part.name_zh, "image_url": i.part.image_url,
                      "checked": i.checked_at is not None, "auto": not is_tech_item(i)} for i in items]
    else:
        checklist = [{"name": p.name_zh, "image_url": p.image_url, "checked": False,
                      "auto": p.rule_type == RuleType.MILEAGE} for p in model_parts(db, wo.vehicle)]
    return {
        "checklist": checklist,
        "started_at": _iso(started),
        "inspect_minutes": INSPECT_MINUTES,
        "visits": list(visits.values())[:3],
    }


def events_view(wo: WorkOrder) -> list[dict]:
    return [{"id": e.id, "type": e.type, "message": e.message, "time": _iso(e.created_at)}
            for e in sorted(wo.events, key=lambda e: e.id)]


def summary_view(db: Session, wo: WorkOrder) -> dict:
    """交車摘要：今天不用換／今天完成／延後＋回廠提醒。"""
    reminders = {r.part_id: r for r in db.query(Reminder).filter_by(work_order_id=wo.id)}
    done, deferred, normal = [], [], []
    for item in wo.items:
        view = item_view(item)
        if item.customer_choice == Choice.TODAY:
            done.append(view)
        elif item.customer_choice == Choice.DEFER:
            r = reminders.get(item.part_id)
            if r:
                view["reminder"] = reminder_view(r)
            deferred.append(view)
        elif item.level == Level.NORMAL:
            normal.append(view)
    return {"order": order_view(wo, include_items=False), "done": done, "deferred": deferred,
            "normal": normal, "paid_total": sum(i["price"] for i in done)}
