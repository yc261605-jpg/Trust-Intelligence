"""第 1 步檢查：資料有沒有正確寫入，以及 find_last_replacement 對不對。

執行：python -m tests.check_step1
"""
from datetime import date

from backend.database import SessionLocal
from backend.history import find_last_replacement
from backend.models import Part, Vehicle

# (車牌, 料號) → 應該得到的 (公里數, 日期)
EXPECTED = {
    ("ABC-1234", "TI-P001"): (20050, date(2026, 8, 15)),  # 有兩筆，取較新的
    ("ABC-1234", "TI-P004"): (20050, date(2026, 8, 15)),
    ("ABC-1234", "TI-P007"): (0, date(2026, 2, 6)),       # 沒紀錄 → 交車日
    ("BCD-5678", "TI-P001"): (10020, date(2026, 6, 20)),
    ("BCD-5678", "TI-P004"): (0, date(2026, 2, 13)),
    ("CDE-9012", "TI-P001"): (0, date(2026, 2, 20)),
}


def main():
    db = SessionLocal()
    try:
        n_parts = db.query(Part).count()
        n_vehicles = db.query(Vehicle).count()
        print(f"零件 {n_parts} 筆（應為 14）、車輛 {n_vehicles} 台（應為 3）")

        passed = 0
        for (plate, part_no), expected in EXPECTED.items():
            vehicle = db.query(Vehicle).filter_by(plate=plate).one()
            part = db.query(Part).filter_by(part_no=part_no).one()
            got = find_last_replacement(db, vehicle, part)
            ok = tuple(got) == expected
            passed += ok
            mark = "OK " if ok else "錯誤"
            print(f"[{mark}] {plate} {part.name_zh}：得到 {got}，應為 {expected}")

        print(f"\n{passed}/{len(EXPECTED)} 通過")
    finally:
        db.close()


if __name__ == "__main__":
    main()
