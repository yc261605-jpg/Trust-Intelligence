"""重建資料庫並寫入模擬資料（車型、零件、3 台示範車、保養紀錄）。

執行：python -m backend.seed
注意：會清空所有資料（含工單與對話）重來。工單請從管理平台「接待建單」建立。
"""
from . import seed_data as D
from .database import SCHEMA_VERSION, SessionLocal, reset_db
from .models import Meta, ModelPart, Part, ServiceHistory, Vehicle, VehicleModel


def clear_uploads() -> int:
    """刪掉技師上傳的照片（資料庫清空後這些照片已經沒有工單對應）。"""
    from .config import settings
    removed = 0
    if settings.upload_dir.exists():
        for f in settings.upload_dir.rglob("*"):
            if f.is_file() and f.name != ".gitkeep":
                f.unlink(missing_ok=True)
                removed += 1
    return removed


def seed() -> None:
    reset_db()
    db = SessionLocal()
    try:
        model = VehicleModel(**D.VEHICLE_MODEL)
        db.add(model)
        db.flush()

        parts_by_no: dict[str, Part] = {}
        for order, p in enumerate(D.PARTS, start=1):
            part = Part(image_url=f"/static/parts/{p['part_no']}.jpg", source="原廠保養手冊（示意）", **p)
            db.add(part)
            db.flush()
            db.add(ModelPart(model_id=model.id, part_id=part.id, sort_order=order))
            parts_by_no[part.part_no] = part

        vehicles_by_plate: dict[str, Vehicle] = {}
        for v in D.VEHICLES:
            vehicle = Vehicle(model_id=model.id, **v)
            db.add(vehicle)
            db.flush()
            vehicles_by_plate[vehicle.plate] = vehicle

        for plate, part_no, replaced_on, km in D.SERVICE_HISTORY:
            db.add(ServiceHistory(vehicle_id=vehicles_by_plate[plate].id, part_id=parts_by_no[part_no].id,
                                  replaced_on=replaced_on, replaced_km=km))
        db.add(Meta(key="schema_version", value=SCHEMA_VERSION))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("資料庫已重建：1 個車型、%d 個零件、%d 台車、%d 筆保養紀錄"
          % (len(D.PARTS), len(D.VEHICLES), len(D.SERVICE_HISTORY)))
    print("示範車牌：" + "、".join(v["plate"] for v in D.VEHICLES) + "（請從管理平台接待建單）")
