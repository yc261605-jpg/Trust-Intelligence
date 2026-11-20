"""查詢某台車某個零件「上次更換」的公里數與日期。

規則引擎用它算剩餘公里：剩餘公里 = 建議間隔公里 − (目前公里 − 上次更換公里)
"""
from datetime import date

from sqlalchemy.orm import Session

from .models import Part, ServiceHistory, Vehicle


def find_last_replacement(db: Session, vehicle: Vehicle, part: Part) -> tuple[int, date]:
    """回傳 (上次更換公里數, 上次更換日期)。沒有紀錄時視為交車當天是新的。"""
    record = (
        db.query(ServiceHistory)
        .filter(ServiceHistory.vehicle_id == vehicle.id, ServiceHistory.part_id == part.id)
        .order_by(ServiceHistory.replaced_km.desc())
        .first()
    )
    if record is None:
        return 0, vehicle.delivered_on
    return record.replaced_km, record.replaced_on
