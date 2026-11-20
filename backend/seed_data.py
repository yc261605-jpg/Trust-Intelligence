"""模擬資料。所有料號、價格、門檻、間隔、里程都是示意，不代表 Toyota 官方規格或報價。

這個檔案只放資料，不放邏輯；seed.py 會讀它寫進資料庫，
第 2 步的規則引擎測試也會用 SCENARIO_INSPECTIONS 和 EXPECTED_LEVELS。
"""
from datetime import date

DEMO_TODAY = date(2026, 11, 1)  # 規則引擎測試用的「今天」

VEHICLE_MODEL = {
    "name": "RAV4 2.5 Hybrid GR Sport 4WD",
    "year": 2026,
    "powertrain": "2.5 油電",
    "drivetrain": "E-Four 4WD",
    "image_url": "/static/img/hero_service_bay.jpg",
}

# 欄位順序：part_no, name_zh, category, rule_type, unit, safe_min, warn_min,
#           interval_km, interval_months, warn_km, safety_critical,
#           part_price, labor_price, labor_minutes, explain_text, defer_impact_text
PARTS = [
    dict(part_no="TI-P001", name_zh="機油（0W-16）", category="引擎", rule_type="mileage",
         interval_km=10000, interval_months=12, warn_km=1000, safety_critical=False,
         part_price=1100, labor_price=300, labor_minutes=20,
         explain_text="機油負責潤滑與散熱，用久了會變稀、髒污，保護力下降。",
         defer_impact_text="短期延後影響不大，建議 1,000 km 內更換。"),
    dict(part_no="TI-P002", name_zh="機油芯", category="引擎", rule_type="mileage",
         interval_km=10000, interval_months=12, warn_km=1000, safety_critical=False,
         part_price=250, labor_price=0, labor_minutes=0,
         explain_text="過濾機油中的雜質，通常和機油一起更換。",
         defer_impact_text="和機油一起延後即可。"),
    dict(part_no="TI-P003", name_zh="引擎空氣濾網", category="引擎", rule_type="mileage",
         interval_km=40000, interval_months=48, warn_km=5000, safety_critical=False,
         part_price=750, labor_price=150, labor_minutes=10,
         explain_text="過濾進入引擎的空氣，太髒會影響油耗與動力。",
         defer_impact_text="可延後至下次保養再檢查。"),
    dict(part_no="TI-P004", name_zh="冷氣濾網", category="空調", rule_type="mileage",
         interval_km=20000, interval_months=12, warn_km=2000, safety_critical=False,
         part_price=600, labor_price=150, labor_minutes=10,
         explain_text="過濾車內空氣中的灰塵與花粉，太髒會有異味、風量變小。",
         defer_impact_text="不影響行車安全，可能有異味或風量變小。"),
    dict(part_no="TI-P005", defer_months=3, name_zh="前輪煞車來令片", category="煞車", rule_type="measure",
         unit="mm", safe_min=3.0, warn_min=4.0, safety_critical=True,
         part_price=2800, labor_price=700, labor_minutes=60,
         explain_text="來令片太薄會讓煞車距離變長，低於安全門檻必須更換。",
         defer_impact_text="建議 3,000 km 內回廠複查厚度。"),
    dict(part_no="TI-P006", defer_months=3, name_zh="後輪煞車來令片", category="煞車", rule_type="measure",
         unit="mm", safe_min=3.0, warn_min=4.0, safety_critical=True,
         part_price=2500, labor_price=700, labor_minutes=60,
         explain_text="來令片太薄會讓煞車距離變長，低於安全門檻必須更換。",
         defer_impact_text="建議 3,000 km 內回廠複查厚度。"),
    dict(part_no="TI-P007", defer_months=3, name_zh="前輪胎（2 條）", category="輪胎", rule_type="measure",
         unit="mm", safe_min=1.6, warn_min=3.0, safety_critical=True,
         part_price=13000, labor_price=800, labor_minutes=40,
         explain_text="胎紋太淺會降低排水與抓地力，雨天容易打滑；低於法規值必須更換。",
         defer_impact_text="雨天抓地力下降，建議 3 個月內更換。"),
    dict(part_no="TI-P008", defer_months=3, name_zh="後輪胎（2 條）", category="輪胎", rule_type="measure",
         unit="mm", safe_min=1.6, warn_min=3.0, safety_critical=True,
         part_price=13000, labor_price=800, labor_minutes=40,
         explain_text="胎紋太淺會降低排水與抓地力，雨天容易打滑；低於法規值必須更換。",
         defer_impact_text="雨天抓地力下降，建議 3 個月內更換。"),
    dict(part_no="TI-P009", defer_months=3, name_zh="12V 電瓶", category="電系", rule_type="measure",
         unit="%", safe_min=40, warn_min=70, safety_critical=False,
         part_price=4200, labor_price=300, labor_minutes=20,
         explain_text="12V 電瓶負責啟動油電系統與車上電器，健康度太低可能無法發動。",
         defer_impact_text="可能突然無法發動，建議 3 個月內複查。"),
    dict(part_no="TI-P010", name_zh="煞車油", category="煞車", rule_type="mileage",
         interval_km=40000, interval_months=24, warn_km=5000, safety_critical=True,
         part_price=900, labor_price=600, labor_minutes=40,
         explain_text="煞車油會吸收水氣，含水量高時煞車力道會變差。",
         defer_impact_text="過期後煞車性能可能下降。"),
    dict(part_no="TI-P011", defer_months=6, name_zh="前雨刷", category="外觀", rule_type="inspect",
         safety_critical=False,
         part_price=900, labor_price=0, labor_minutes=10,
         explain_text="雨刷膠條老化會刮不乾淨，影響雨天視線。",
         defer_impact_text="雨天視線較差，可自行選擇時間更換。"),
    dict(part_no="TI-P012", defer_months=6, name_zh="油電電池冷卻進風濾網", category="油電系統", rule_type="inspect",
         safety_critical=False,
         part_price=500, labor_price=300, labor_minutes=20,
         explain_text="油電電池靠這個進風口散熱，堵塞會讓電池溫度偏高。",
         defer_impact_text="下次保養再檢查即可。"),
    dict(part_no="TI-P013", name_zh="變頻器冷卻液", category="油電系統", rule_type="mileage",
         interval_km=150000, interval_months=120, warn_km=10000, safety_critical=False,
         part_price=1200, labor_price=900, labor_minutes=45,
         explain_text="負責幫油電系統的變頻器散熱，更換間隔很長。",
         defer_impact_text="接近更換里程時再處理即可。"),
    dict(part_no="TI-P014", name_zh="E-Four 後差速器油", category="傳動", rule_type="mileage",
         interval_km=60000, interval_months=72, warn_km=5000, safety_critical=False,
         part_price=800, labor_price=500, labor_minutes=30,
         explain_text="潤滑後軸電動馬達的齒輪組。",
         defer_impact_text="接近更換里程時再處理即可。"),
]

# 三位車主（全部 2026 年 2 月交車，交車時 0 km）
VEHICLES = [
    dict(plate="ABC-1234", owner_name="王先生", owner_phone="0912-345-678",
         delivered_on=date(2026, 2, 6)),
    dict(plate="BCD-5678", owner_name="林小姐", owner_phone="0923-456-789",
         delivered_on=date(2026, 2, 13)),
    dict(plate="CDE-9012", owner_name="陳先生", owner_phone="0934-567-890",
         delivered_on=date(2026, 2, 20)),
]

# 過去更換紀錄：(車牌, 料號, 更換日期, 更換時公里數)
# 沒有紀錄的零件，視為交車當天（0 km）是新的
SERVICE_HISTORY = [
    ("ABC-1234", "TI-P001", date(2026, 5, 9), 10030),
    ("ABC-1234", "TI-P002", date(2026, 5, 9), 10030),
    ("ABC-1234", "TI-P001", date(2026, 8, 15), 20050),
    ("ABC-1234", "TI-P002", date(2026, 8, 15), 20050),
    ("ABC-1234", "TI-P004", date(2026, 8, 15), 20050),
    ("BCD-5678", "TI-P001", date(2026, 6, 20), 10020),
    ("BCD-5678", "TI-P002", date(2026, 6, 20), 10020),
]

# 本次進廠的公里數
CURRENT_KM = {"ABC-1234": 31200, "BCD-5678": 19800, "CDE-9012": 9950}

# 技師在檢查頁會輸入的內容（量測型填數值，技師判定型填狀態；里程型不用填）
# 格式：料號: (量測值, 技師狀態, 原因)
SCENARIO_INSPECTIONS = {
    "ABC-1234": {
        "TI-P005": (3.6, None, "來令片剩 3.6 mm，接近安全門檻"),
        "TI-P006": (5.0, None, None),
        "TI-P007": (1.4, None, "胎紋 1.4 mm，低於法規 1.6 mm"),
        "TI-P008": (3.5, None, None),
        "TI-P009": (82, None, None),
        "TI-P011": (None, "suggest", "膠條硬化，刮水有殘痕"),
        "TI-P012": (None, "normal", None),
    },
    "BCD-5678": {
        "TI-P005": (6.5, None, None),
        "TI-P006": (7.0, None, None),
        "TI-P007": (5.2, None, None),
        "TI-P008": (5.4, None, None),
        "TI-P009": (60, None, "電瓶檢測健康度 60%，CCA 偏低"),
        "TI-P011": (None, "normal", None),
        "TI-P012": (None, "normal", None),
    },
    "CDE-9012": {
        "TI-P005": (8.5, None, None),
        "TI-P006": (8.8, None, None),
        "TI-P007": (6.8, None, None),
        "TI-P008": (6.9, None, None),
        "TI-P009": (92, None, None),
        "TI-P011": (None, "normal", None),
        "TI-P012": (None, "normal", None),
    },
}

# 規則引擎跑完後「應該」得到的分級（第 2 步的測試會拿來比對）
# 沒列出的料號 = normal
EXPECTED_LEVELS = {
    "ABC-1234": {
        "TI-P007": "immediate",   # 胎紋 1.4 < 1.6
        "TI-P005": "deferrable",  # 3.0 ≤ 3.6 < 4.0
        "TI-P001": "deferrable",  # 機油逾期 1,150 km，非安全關鍵
        "TI-P002": "deferrable",
        "TI-P011": "deferrable",  # 技師選「建議更換」
    },
    "BCD-5678": {
        "TI-P009": "deferrable",  # 40 ≤ 60 < 70
        "TI-P004": "deferrable",  # 剩 200 km ≤ 2,000
        "TI-P001": "deferrable",  # 剩 220 km ≤ 1,000
        "TI-P002": "deferrable",
    },
    "CDE-9012": {
        "TI-P001": "deferrable",  # 剩 50 km
        "TI-P002": "deferrable",
    },
}
