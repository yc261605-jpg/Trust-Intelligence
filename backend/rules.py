"""規則引擎：唯一決定分級的地方。

同樣的輸入永遠得到同樣的結果；Agent 只能解釋，不能改變結論。
分級：immediate（立即處理）、deferrable（可延後）、normal（目前正常）
"""
from dataclasses import dataclass
from datetime import date

from .models import Level, Part, RuleType, TechStatus

LEVEL_ZH = {
    Level.IMMEDIATE: "立即處理",
    Level.DEFERRABLE: "可延後",
    Level.NORMAL: "目前正常",
}


@dataclass
class RuleResult:
    level: str
    remaining_km: int | None = None
    remaining_months: int | None = None
    basis: str = ""   # 給車主與 Agent 看的判斷依據（一句話）


def months_between(start: date, end: date) -> int:
    """兩個日期之間經過幾個整月。"""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _fmt(value: float) -> str:
    return f"{value:g}"


def evaluate(
    part: Part,
    *,
    current_km: int,
    today: date,
    last_km: int,
    last_date: date,
    measured_value: float | None = None,
    tech_status: str | None = None,
) -> RuleResult:
    """依零件的規則類型分級。技師勾選「必須更換」一律升為立即處理（只能升級，不能降級）。"""
    if part.rule_type == RuleType.MEASURE:
        result = _evaluate_measure(part, measured_value)
    elif part.rule_type == RuleType.MILEAGE:
        result = _evaluate_mileage(part, current_km, today, last_km, last_date)
    elif part.rule_type == RuleType.INSPECT:
        result = _evaluate_inspect(tech_status)
    else:
        raise ValueError(f"未知的規則類型：{part.rule_type}")

    if tech_status == TechStatus.MUST and result.level != Level.IMMEDIATE:
        result.level = Level.IMMEDIATE
        result.basis = "技師現場判定必須更換"
    return result


def _evaluate_measure(part: Part, value: float | None) -> RuleResult:
    if value is None:
        raise ValueError(f"{part.name_zh} 需要量測值")
    unit = part.unit or ""
    if value < part.safe_min:
        return RuleResult(Level.IMMEDIATE,
                          basis=f"量測 {_fmt(value)} {unit}，低於安全門檻 {_fmt(part.safe_min)} {unit}")
    if value < part.warn_min:
        return RuleResult(Level.DEFERRABLE,
                          basis=f"量測 {_fmt(value)} {unit}，已接近門檻（預警 {_fmt(part.warn_min)} {unit}）")
    return RuleResult(Level.NORMAL, basis=f"量測 {_fmt(value)} {unit}，狀況良好")


def _evaluate_mileage(part: Part, current_km: int, today: date, last_km: int, last_date: date) -> RuleResult:
    remaining_km = part.interval_km - (current_km - last_km) if part.interval_km else None
    remaining_months = (
        part.interval_months - months_between(last_date, today) if part.interval_months else None
    )

    overdue_km = remaining_km is not None and remaining_km <= 0
    overdue_month = remaining_months is not None and remaining_months <= 0
    if overdue_km or overdue_month:
        if overdue_km:
            basis = f"已超過建議里程 {abs(remaining_km):,} km"
        else:
            basis = f"已超過建議期限 {abs(remaining_months)} 個月"
        level = Level.IMMEDIATE if part.safety_critical else Level.DEFERRABLE
        return RuleResult(level, remaining_km, remaining_months, basis)

    near_km = remaining_km is not None and part.warn_km is not None and remaining_km <= part.warn_km
    near_month = remaining_months is not None and remaining_months <= 1
    if near_km or near_month:
        basis = f"距建議更換剩 {remaining_km:,} km" if near_km else f"距建議更換剩 {remaining_months} 個月"
        return RuleResult(Level.DEFERRABLE, remaining_km, remaining_months, basis)

    return RuleResult(Level.NORMAL, remaining_km, remaining_months,
                      f"距建議更換還有 {remaining_km:,} km")


def _evaluate_inspect(tech_status: str | None) -> RuleResult:
    if tech_status == TechStatus.MUST:
        return RuleResult(Level.IMMEDIATE, basis="技師現場判定必須更換")
    if tech_status == TechStatus.SUGGEST:
        return RuleResult(Level.DEFERRABLE, basis="技師現場判定建議更換")
    if tech_status == TechStatus.NORMAL:
        return RuleResult(Level.NORMAL, basis="技師檢查狀況正常")
    raise ValueError("技師判定型項目需要勾選狀態")
