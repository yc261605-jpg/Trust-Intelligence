"""技師端 API：工單列表、開始檢查、公里數、逐項存檔（含照片）、送出、施工回報。"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .agent import make_brief
from .config import settings
from .database import get_db
from .deps import require_staff
from .history import find_last_replacement
from .models import InspectionItem, Photo, WorkOrder
from .services import (
    complete_order, finish_item, item_view, order_view, save_item, set_mileage, start_inspection,
    start_item, submit_inspection,
)

router = APIRouter(prefix="/api/tech", tags=["技師端"], dependencies=[Depends(require_staff)])

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024


def _get_order(db: Session, order_id: int) -> WorkOrder:
    wo = db.get(WorkOrder, order_id)
    if wo is None:
        raise HTTPException(404, "找不到工單")
    return wo


def _get_item(db: Session, item_id: int) -> InspectionItem:
    item = db.get(InspectionItem, item_id)
    if item is None:
        raise HTTPException(404, "找不到檢查項目")
    return item


@router.get("/work-orders")
def list_orders(db: Session = Depends(get_db)):
    return [order_view(wo, include_items=False)
            for wo in db.query(WorkOrder).order_by(WorkOrder.id.desc()).all()]


@router.get("/work-orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    wo = _get_order(db, order_id)
    data = order_view(wo, include_items=False)
    data["items"] = [item_view(i, find_last_replacement(db, wo.vehicle, i.part)) for i in wo.items]
    return data


@router.post("/work-orders/{order_id}/start")
def start(order_id: int, db: Session = Depends(get_db)):
    wo = _get_order(db, order_id)
    start_inspection(db, wo)
    db.commit()
    return get_order(order_id, db)


class MileageIn(BaseModel):
    current_km: int


@router.put("/work-orders/{order_id}/mileage")
def mileage(order_id: int, body: MileageIn, db: Session = Depends(get_db)):
    if body.current_km < 0:
        raise HTTPException(400, "公里數不能是負數")
    if body.current_km > 999_999:
        raise HTTPException(400, "公里數不能超過 999,999 km")
    wo = _get_order(db, order_id)
    set_mileage(db, wo, body.current_km, date.today())
    db.commit()
    return get_order(order_id, db)


class ItemIn(BaseModel):
    measured_value: float | None = None
    tech_status: str | None = None
    reason: str | None = None


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemIn, db: Session = Depends(get_db)):
    """技師完成一項：存輸入並立即分級。"""
    item = _get_item(db, item_id)
    if body.tech_status not in (None, "normal", "suggest", "must"):
        raise HTTPException(400, "狀態只能是 normal、suggest、must")
    data = body.model_dump()
    if data["reason"] is not None:
        data["reason"] = data["reason"].strip() or None
    wo = item.work_order
    save_item(db, wo, item, data, date.today())
    db.commit()
    return item_view(item, find_last_replacement(db, wo.vehicle, item.part))


@router.post("/work-orders/{order_id}/submit")
def submit(order_id: int, db: Session = Depends(get_db)):
    wo = _get_order(db, order_id)
    submit_inspection(db, wo, date.today())
    wo.brief = make_brief(wo)  # 給專員的 30 秒說明稿
    db.commit()
    return get_order(order_id, db)


@router.post("/items/{item_id}/photos")
async def upload_photo(item_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    item = _get_item(db, item_id)
    ext = ("." + file.filename.rsplit(".", 1)[-1].lower()) if file.filename and "." in file.filename else ".jpg"
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "只接受 JPG、PNG、WEBP、HEIC 照片")
    content = await file.read()
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(400, "照片超過 10 MB")
    rel = f"wo_{item.work_order_id}/item_{item.id}_{uuid.uuid4().hex[:8]}{ext}"
    path = settings.upload_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    db.add(Photo(item_id=item.id, file_path=rel))
    db.commit()
    return {"url": f"/uploads/{rel}"}


@router.post("/items/{item_id}/start")
def item_start(item_id: int, db: Session = Depends(get_db)):
    item = _get_item(db, item_id)
    start_item(db, item.work_order, item)
    db.commit()
    return get_order(item.work_order_id, db)


@router.post("/items/{item_id}/done")
def item_done(item_id: int, db: Session = Depends(get_db)):
    item = _get_item(db, item_id)
    finish_item(db, item.work_order, item)
    db.commit()
    return get_order(item.work_order_id, db)


@router.post("/work-orders/{order_id}/complete")
def complete(order_id: int, db: Session = Depends(get_db)):
    wo = _get_order(db, order_id)
    complete_order(db, wo)
    db.commit()
    return get_order(order_id, db)
