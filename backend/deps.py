"""權限檢查。

- 技師端與管理平台：請求標頭帶 X-Staff-Key（.env 的 STAFF_PASSWORD）
- 車主端：登入後拿到簽章憑證，請求標頭帶 Authorization: Bearer <token>，只能看自己的工單
"""
import hashlib
import hmac
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import WorkOrder

CUSTOMER_TOKEN_HOURS = 24


def require_staff(x_staff_key: str | None = Header(default=None)) -> None:
    if not x_staff_key or not hmac.compare_digest(x_staff_key, settings.staff_password):
        raise HTTPException(401, "員工密碼錯誤")


def _sign(payload: str) -> str:
    return hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_customer_token(work_order_id: int) -> str:
    payload = f"{work_order_id}.{int(time.time())}"
    return f"{payload}.{_sign(payload)}"


def require_customer(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WorkOrder:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "請先登入")
    token = authorization.removeprefix("Bearer ")
    try:
        wo_id, issued, sig = token.split(".")
        valid = hmac.compare_digest(sig, _sign(f"{wo_id}.{issued}"))
        expired = time.time() - int(issued) > CUSTOMER_TOKEN_HOURS * 3600
    except ValueError:
        valid, expired = False, False
    if not valid or expired:
        raise HTTPException(401, "登入已失效，請重新掃描 QR Code")
    wo = db.get(WorkOrder, int(wo_id))
    if wo is None:
        raise HTTPException(401, "找不到工單，請重新掃描 QR Code")
    return wo
