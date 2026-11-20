"""車主端 API：登入、決策卡、逐項確認、進度、交車摘要、Agent 對話、轉接真人。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import agent
from .database import get_db
from .deps import make_customer_token, require_customer
from .models import ChatMessage, HandoffRequest, WorkOrder, WorkOrderStatus
from .services import add_event, apply_decision, events_view, order_view, summary_view, waiting_view

router = APIRouter(prefix="/api/customer", tags=["車主端"])

MAX_FAILED_LOGINS = 5


class LoginIn(BaseModel):
    token: str
    plate: str


def _plate_key(plate: str) -> str:
    return plate.strip().upper().replace(" ", "").replace("-", "")


def _mask(plate: str) -> str:
    head, _, tail = plate.partition("-")
    return f"{head}-{'*' * len(tail)}" if tail else plate[:3] + "*" * (len(plate) - 3)


@router.get("/preview")
def preview(token: str, db: Session = Depends(get_db)):
    """掃 QR 後的登入頁：只顯示車型與遮蔽的車牌，讓車主確認是自己的車。"""
    wo = db.query(WorkOrder).filter_by(qr_token=token).first()
    if wo is None:
        raise HTTPException(404, "這個 QR Code 已失效，請向服務人員索取新的")
    v = wo.vehicle
    return {"model": f"{v.model.year} {v.model.name}", "image_url": v.model.image_url,
            "plate_hint": _mask(v.plate), "owner_name": v.owner_name}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    wo = db.query(WorkOrder).filter_by(qr_token=body.token).first()
    if wo is None:
        raise HTTPException(404, "QR Code 無效，請向服務人員確認")
    if wo.failed_logins >= MAX_FAILED_LOGINS:
        raise HTTPException(423, "輸入錯誤太多次，請洽服務人員重新產生 QR Code")
    if _plate_key(body.plate) != _plate_key(wo.vehicle.plate):
        wo.failed_logins += 1
        db.commit()
        left = MAX_FAILED_LOGINS - wo.failed_logins
        raise HTTPException(401, f"車牌不符，請再確認一次（還可以試 {left} 次）")
    wo.failed_logins = 0
    db.commit()
    return {"access_token": make_customer_token(wo.id)}


@router.get("/work-order")
def my_order(wo: WorkOrder = Depends(require_customer), db: Session = Depends(get_db)):
    data = order_view(wo)
    data.pop("brief", None)  # 專員說明稿只給員工看
    # 技師送出前，車主只看到檢查進度，不看結果
    if wo.status in (WorkOrderStatus.CREATED, WorkOrderStatus.INSPECTING):
        data["items"] = []
        data["waiting"] = waiting_view(db, wo)
    data["events"] = events_view(wo)
    return data


class DecisionIn(BaseModel):
    choices: dict[int, str]


@router.post("/decision")
def decide(body: DecisionIn, wo: WorkOrder = Depends(require_customer), db: Session = Depends(get_db)):
    apply_decision(db, wo, body.choices)
    db.commit()
    return order_view(wo)


@router.get("/summary")
def summary(wo: WorkOrder = Depends(require_customer), db: Session = Depends(get_db)):
    if wo.status != WorkOrderStatus.COMPLETED:
        raise HTTPException(400, "完工後才有交車摘要")
    return summary_view(db, wo)


# ---------- Agent 與轉接 ----------

@router.get("/chat")
def chat_history(wo: WorkOrder = Depends(require_customer), db: Session = Depends(get_db)):
    rows = db.query(ChatMessage).filter_by(work_order_id=wo.id).order_by(ChatMessage.id).all()
    handoff = db.query(HandoffRequest).filter(
        HandoffRequest.work_order_id == wo.id, HandoffRequest.status != "closed").first()
    return {
        "messages": [{"id": m.id, "role": m.role, "content": m.content,
                      "time": m.created_at.isoformat(timespec="minutes")} for m in rows],
        "handoff_status": handoff.status if handoff else None,
    }


class ChatIn(BaseModel):
    message: str


@router.post("/chat")
def chat(body: ChatIn, wo: WorkOrder = Depends(require_customer), db: Session = Depends(get_db)):
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "請輸入訊息")
    if len(text) > 500:
        raise HTTPException(400, "訊息太長，請精簡在 500 字內")
    db.add(ChatMessage(work_order_id=wo.id, role="customer", content=text))
    db.flush()

    # 已轉接真人：訊息直接給專員，Agent 不回答
    handoff = db.query(HandoffRequest).filter(
        HandoffRequest.work_order_id == wo.id, HandoffRequest.status != "closed").first()
    if handoff:
        db.commit()
        return {"reply": None, "handoff_active": True, "suggest_handoff": False}

    reply = agent.answer(db, wo, text)
    db.add(ChatMessage(work_order_id=wo.id, role="agent", content=reply.text))
    db.commit()
    return {"reply": reply.text, "sources": reply.sources, "suggest_handoff": reply.suggest_handoff,
            "handoff_active": False, "engine": reply.engine}


@router.post("/handoff")
def request_handoff(wo: WorkOrder = Depends(require_customer), db: Session = Depends(get_db)):
    existing = db.query(HandoffRequest).filter(
        HandoffRequest.work_order_id == wo.id, HandoffRequest.status != "closed").first()
    if existing is None:
        db.add(HandoffRequest(work_order_id=wo.id))
        db.add(ChatMessage(work_order_id=wo.id, role="agent",
                           content="已幫你通知服務專員，專員會在這裡直接回覆你，請稍候。"))
        add_event(db, wo, "handoff", "車主要求轉接服務專員")
        db.commit()
    return {"ok": True}
