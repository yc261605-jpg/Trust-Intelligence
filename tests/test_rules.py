"""規則引擎測試：三個車主情境的分級要和 seed_data.EXPECTED_LEVELS 一致。"""
from datetime import date

import pytest

from backend import seed_data as D
from backend.database import SessionLocal
from backend.models import Level, Part, Vehicle
from backend.rules import evaluate, months_between
from backend.services import create_work_order, save_item, set_mileage, start_inspection


def _inspect(db, plate):
    """照模擬情境跑一次：輸入公里數 → 逐項存檔，回傳 {料號: 分級}。"""
    vehicle = db.query(Vehicle).filter_by(plate=plate).one()
    wo = create_work_order(db, vehicle)
    start_inspection(db, wo)
    set_mileage(db, wo, D.CURRENT_KM[plate], D.DEMO_TODAY)
    for item in wo.items:
        data = D.SCENARIO_INSPECTIONS[plate].get(item.part.part_no)
        if data:
            value, status, reason = data
            save_item(db, wo, item, {"measured_value": value, "tech_status": status, "reason": reason},
                      D.DEMO_TODAY)
    return {i.part.part_no: i.level for i in wo.items}


@pytest.mark.parametrize("plate", list(D.EXPECTED_LEVELS))
def test_scenarios(fresh_db, plate):
    db = SessionLocal()
    try:
        levels = _inspect(db, plate)
        expected = D.EXPECTED_LEVELS[plate]
        for part_no, got in levels.items():
            want = expected.get(part_no, Level.NORMAL)
            assert got == want, f"{plate} {part_no}: {got} != {want}"
    finally:
        db.close()


def _part(**kw):
    base = dict(part_no="X", name_zh="測試", category="t", rule_type="measure",
                unit="mm", safe_min=3.0, warn_min=4.0, safety_critical=True,
                interval_km=None, interval_months=None, warn_km=None)
    base.update(kw)
    return Part(**base)


def test_measure_boundaries():
    p = _part()
    kw = dict(current_km=0, today=date(2026, 1, 1), last_km=0, last_date=date(2026, 1, 1))
    assert evaluate(p, measured_value=2.9, **kw).level == Level.IMMEDIATE
    assert evaluate(p, measured_value=3.0, **kw).level == Level.DEFERRABLE
    assert evaluate(p, measured_value=4.0, **kw).level == Level.NORMAL


def test_mileage_overdue_safety_is_immediate():
    p = _part(rule_type="mileage", interval_km=40000, interval_months=24, warn_km=5000)
    r = evaluate(p, current_km=41000, today=date(2026, 1, 1), last_km=0, last_date=date(2025, 6, 1))
    assert r.level == Level.IMMEDIATE and r.remaining_km == -1000


def test_mileage_by_months():
    p = _part(rule_type="mileage", safety_critical=False, interval_km=10000, interval_months=12, warn_km=1000)
    r = evaluate(p, current_km=3000, today=date(2026, 3, 1), last_km=0, last_date=date(2025, 2, 1))
    assert r.level == Level.DEFERRABLE  # 13 個月，逾期但非安全關鍵


def test_tech_must_escalates():
    p = _part()
    r = evaluate(p, current_km=0, today=date(2026, 1, 1), last_km=0, last_date=date(2026, 1, 1),
                 measured_value=6.0, tech_status="must")
    assert r.level == Level.IMMEDIATE


def test_months_between():
    assert months_between(date(2026, 2, 20), date(2026, 11, 1)) == 8
    assert months_between(date(2026, 2, 1), date(2026, 11, 1)) == 9
