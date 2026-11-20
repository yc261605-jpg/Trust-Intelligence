"""管理平台 API：接待建單、QR 與驗證碼、工單總覽、轉接中心、零件與規則維護。"""
import io
import socket
from datetime import date
from urllib.parse import urlsplit

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .deps import require_staff
from .models import (
    ChatMessage, HandoffRequest, Part, Reminder, Vehicle, VehicleModel, WorkOrder,
)
from .agent import make_brief
from .services import (
    add_event, create_work_order, events_view, order_view, regenerate_qr, reminder_view,
)

router = APIRouter(prefix="/api/admin", tags=["管理平台"], dependencies=[Depends(require_staff)])


# ---------- 公開網址（給 QR 用） ----------
# 手機連不上最常見的原因：
#   1. uvicorn 沒加 --host 0.0.0.0（只聽本機，手機一定連不上）
#   2. 自動偵測選到 VPN、WSL、Hyper-V、Docker 的虛擬網卡 IP（通常是 172.x）
#   3. Windows 防火牆擋住 8000 埠，或 Wi-Fi 被設成「公用網路」
#   4. 手機跟電腦不在同一個 Wi-Fi（訪客網路通常會互相隔離）
# 這裡把候選 IP 都列出來、自我檢查能不能連到，並允許在管理平台直接切換。

_runtime_base: str | None = None


def _ip_rank(ip: str) -> int:
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    if ip.startswith("172."):
        second = int(ip.split(".")[1])
        if 16 <= second <= 31:
            return 3                     # 常是 WSL／Hyper-V／Docker 虛擬網卡
    if ip.startswith("169.254.") or ip.startswith("127."):
        return 9
    return 2


def _route_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def lan_candidates() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    route = _route_ip()
    if route:
        ips.add(route)
    ips = {ip for ip in ips if _ip_rank(ip) < 9}
    # 預設路由那張網卡優先（同等級時），其次 192.168 → 10 → 其他 → 172.16-31
    return sorted(ips, key=lambda ip: (_ip_rank(ip), ip != route, ip))


def _lan_ip() -> str | None:
    c = lan_candidates()
    return c[0] if c else None


def public_base(request: Request) -> str:
    """手機要連的網址。優先順序：管理平台切換 > PUBLIC_BASE_URL > 自動偵測區網 IP。"""
    if _runtime_base:
        return _runtime_base
    if settings.public_base_url and _configured_alive():
        return settings.public_base_url
    parts = urlsplit(str(request.base_url))
    host = parts.hostname or "localhost"
    if host in ("localhost", "127.0.0.1"):
        host = _lan_ip() or host
    scheme = parts.scheme
    # 透過 cloudflared 等隧道開管理平台時，直接用隧道網址（一定是 https）
    if host.endswith((".trycloudflare.com", ".ngrok-free.app", ".ngrok.io")) or \
            request.headers.get("x-forwarded-proto") == "https":
        return f"https://{host}"
    port = f":{parts.port}" if parts.port else ""
    return f"{scheme}://{host}{port}"


def _configured_alive() -> bool:
    """設定的公開網址如果是已失效的隧道（網域查不到），就改用自動偵測。"""
    host = urlsplit(settings.public_base_url).hostname or ""
    if host.endswith((".trycloudflare.com", ".ngrok-free.app", ".ngrok.io")):
        return _resolves(host)
    return True


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.8):
            return True
    except OSError:
        return False


def customer_url(request: Request, wo: WorkOrder) -> str:
    return f"{public_base(request)}/c/?t={wo.qr_token}"


@router.get("/info")
def info(request: Request):
    return {"public_base_url": public_base(request), "rule_version": settings.rule_version,
            "llm_configured": bool(settings.gemini_api_key), "llm_model": settings.gemini_model}


@router.get("/network")
def network(request: Request):
    """手機連線檢查：目前 QR 網址、候選 IP、伺服器是否有對區網開放。"""
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    base = public_base(request)
    cands = lan_candidates()
    host = urlsplit(base).hostname or ""
    is_local_host = host in ("localhost", "127.0.0.1")
    is_tunnel = base.startswith("https://")
    target = host if (host and not is_local_host) else (cands[0] if cands else "")
    target_port = urlsplit(base).port or port
    listening = None if (is_tunnel or not target) else _reachable(target, target_port)
    return {
        "base": base,
        "source": "manual" if _runtime_base else "env" if (settings.public_base_url and _configured_alive()) else "auto",
        "stale_env": settings.public_base_url if (settings.public_base_url and not _configured_alive()) else None,
        "port": port,
        "candidates": [{"ip": ip, "url": f"http://{ip}:{port}", "virtual": _ip_rank(ip) == 3} for ip in cands],
        "lan_listening": listening,          # False = uvicorn 沒加 --host 0.0.0.0
        "points_to_localhost": is_local_host,
        "tunnel": is_tunnel,
        "tunnel_alive": _resolves(host) if is_tunnel else None,   # False = 隧道網址已失效（cloudflared 關掉或重開過）
    }


class NetworkIn(BaseModel):
    base: str = ""


@router.put("/network")
def set_network(body: NetworkIn, request: Request):
    global _runtime_base
    b = body.base.strip().rstrip("/")
    if b and not b.startswith(("http://", "https://")):
        raise HTTPException(400, "網址要以 http:// 或 https:// 開頭")
    _runtime_base = b or None
    return network(request)


# ---------- 接待建單 ----------

class CreateOrderIn(BaseModel):
    plate: str
    owner_name: str | None = None
    owner_phone: str | None = None


def _normalize_plate(plate: str) -> str:
    return plate.strip().upper().replace(" ", "")


@router.get("/vehicles")
def list_vehicles(db: Session = Depends(get_db)):
    return [
        {"plate": v.plate, "owner_name": v.owner_name, "owner_phone": v.owner_phone,
         "model": f"{v.model.year} {v.model.name}"}
        for v in db.query(Vehicle).order_by(Vehicle.plate)
    ]


@router.post("/work-orders")
def create_order(body: CreateOrderIn, request: Request, db: Session = Depends(get_db)):
    plate = _normalize_plate(body.plate)
    vehicle = db.query(Vehicle).filter_by(plate=plate).first()
    if vehicle is None:
        if not body.owner_name or not body.owner_phone:
            raise HTTPException(404, "查無此車牌，新車請填寫車主姓名與電話")
        model = db.query(VehicleModel).first()
        vehicle = Vehicle(plate=plate, model_id=model.id, owner_name=body.owner_name,
                          owner_phone=body.owner_phone, delivered_on=date.today())
        db.add(vehicle)
        db.flush()
    wo = create_work_order(db, vehicle)
    db.commit()
    return {"order": order_view(wo, include_items=False), "customer_url": customer_url(request, wo)}


@router.post("/work-orders/{order_id}/regenerate-qr")
def regenerate(order_id: int, request: Request, db: Session = Depends(get_db)):
    """QR 遺失或被鎖定時：產生新的 QR，舊的立即失效。"""
    wo = _get_order(db, order_id)
    regenerate_qr(wo)
    db.commit()
    return {"order": order_view(wo, include_items=False), "customer_url": customer_url(request, wo)}


@router.get("/work-orders/{order_id}")
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    wo = _get_order(db, order_id)
    data = order_view(wo)
    data["customer_url"] = customer_url(request, wo)
    data["events"] = events_view(wo)
    return data


@router.post("/work-orders/{order_id}/brief")
def regenerate_brief(order_id: int, db: Session = Depends(get_db)):
    """重新產生專員 30 秒說明稿。"""
    wo = _get_order(db, order_id)
    if not wo.inspected_at:
        raise HTTPException(400, "技師檢查完成後才有說明稿")
    wo.brief = make_brief(wo)
    db.commit()
    return {"brief": wo.brief}


@router.get("/reminders")
def list_reminders(db: Session = Depends(get_db)):
    rows = db.query(Reminder).order_by(Reminder.due_date).all()
    return [reminder_view(r) for r in rows]


@router.get("/work-orders/{order_id}/qr.png")
def qr_png(order_id: int, request: Request, db: Session = Depends(get_db)):
    wo = _get_order(db, order_id)
    img = qrcode.make(customer_url(request, wo), box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@router.get("/work-orders")
def list_orders(db: Session = Depends(get_db)):
    orders = db.query(WorkOrder).order_by(WorkOrder.id.desc()).all()
    result = []
    for wo in orders:
        view = order_view(wo, include_items=False)
        view["customer_url"] = f"/c/?t={wo.qr_token}"
        view["waiting_handoffs"] = sum(
            1 for h in db.query(HandoffRequest).filter_by(work_order_id=wo.id, status="waiting"))
        result.append(view)
    return result


def _get_order(db: Session, order_id: int) -> WorkOrder:
    wo = db.get(WorkOrder, order_id)
    if wo is None:
        raise HTTPException(404, "找不到工單")
    return wo


# ---------- 轉接中心 ----------

@router.get("/handoffs")
def list_handoffs(db: Session = Depends(get_db)):
    rows = db.query(HandoffRequest).filter(HandoffRequest.status != "closed") \
        .order_by(HandoffRequest.id.desc()).all()
    out = []
    for h in rows:
        wo = db.get(WorkOrder, h.work_order_id)
        out.append({"id": h.id, "status": h.status, "work_order_id": wo.id,
                    "plate": wo.vehicle.plate, "owner_name": wo.vehicle.owner_name,
                    "order_status_zh": order_view(wo, include_items=False)["status_zh"],
                    "created_at": h.created_at.isoformat(timespec="minutes")})
    return out


@router.get("/work-orders/{order_id}/messages")
def order_messages(order_id: int, db: Session = Depends(get_db)):
    _get_order(db, order_id)
    rows = db.query(ChatMessage).filter_by(work_order_id=order_id).order_by(ChatMessage.id).all()
    return [{"id": m.id, "role": m.role, "content": m.content,
             "time": m.created_at.isoformat(timespec="minutes")} for m in rows]


class ReplyIn(BaseModel):
    content: str


@router.post("/handoffs/{handoff_id}/reply")
def reply_handoff(handoff_id: int, body: ReplyIn, db: Session = Depends(get_db)):
    h = db.get(HandoffRequest, handoff_id)
    if h is None:
        raise HTTPException(404, "找不到轉接請求")
    if not body.content.strip():
        raise HTTPException(400, "回覆內容不能空白")
    h.status = "handling"
    db.add(ChatMessage(work_order_id=h.work_order_id, role="staff", content=body.content.strip()))
    db.commit()
    return {"ok": True}


@router.post("/handoffs/{handoff_id}/close")
def close_handoff(handoff_id: int, db: Session = Depends(get_db)):
    h = db.get(HandoffRequest, handoff_id)
    if h is None:
        raise HTTPException(404, "找不到轉接請求")
    h.status = "closed"
    wo = db.get(WorkOrder, h.work_order_id)
    add_event(db, wo, "handoff", "服務專員已結束對話")
    db.commit()
    return {"ok": True}


# ---------- 零件與規則 ----------

PART_FIELDS = ["name_zh", "category", "unit", "safe_min", "warn_min", "interval_km",
               "interval_months", "warn_km", "safety_critical", "part_price", "labor_price",
               "labor_minutes", "explain_text", "defer_impact_text", "defer_months"]


@router.get("/parts")
def list_parts(db: Session = Depends(get_db)):
    return [
        {"id": p.id, "part_no": p.part_no, "rule_type": p.rule_type, "image_url": p.image_url,
         **{f: getattr(p, f) for f in PART_FIELDS}}
        for p in db.query(Part).order_by(Part.part_no)
    ]


class PartUpdate(BaseModel):
    name_zh: str | None = None
    category: str | None = None
    unit: str | None = None
    safe_min: float | None = None
    warn_min: float | None = None
    interval_km: int | None = None
    interval_months: int | None = None
    warn_km: int | None = None
    safety_critical: bool | None = None
    part_price: int | None = None
    labor_price: int | None = None
    labor_minutes: int | None = None
    explain_text: str | None = None
    defer_impact_text: str | None = None
    defer_months: int | None = None


@router.put("/parts/{part_id}")
def update_part(part_id: int, body: PartUpdate, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "找不到零件")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    if p.safe_min is not None and p.warn_min is not None and p.safe_min > p.warn_min:
        raise HTTPException(400, "安全門檻不能大於預警值")
    db.commit()
    return {"ok": True}


# ---------- 示範工具 ----------

@router.post("/demo/reset")
def demo_reset():
    """清空並重建模擬資料（Demo 前用）：工單、照片、對話、提醒全部清掉，只留車款、零件與示範車輛。"""
    from .seed import clear_uploads, seed
    seed()
    return {"ok": True, "photos_removed": clear_uploads()}

