"""11 張資料表。欄位對應設計文件「資料庫設計」一節。"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> datetime:
    return datetime.now()


# ---------- 固定選項（用字串存，方便看資料庫） ----------

class RuleType:
    MEASURE = "measure"    # 量測門檻型：胎紋、來令片、電瓶
    MILEAGE = "mileage"    # 里程／時間型：機油、濾網
    INSPECT = "inspect"    # 技師判定型：雨刷


class Level:
    IMMEDIATE = "immediate"    # 立即處理（不可延後）
    DEFERRABLE = "deferrable"  # 可延後
    NORMAL = "normal"          # 目前正常


class TechStatus:  # 技師判定型的勾選
    NORMAL = "normal"
    SUGGEST = "suggest"  # 建議更換
    MUST = "must"        # 必須更換


class WorkOrderStatus:
    CREATED = "created"                      # 已建立
    INSPECTING = "inspecting"                # 檢查中
    AWAITING_CUSTOMER = "awaiting_customer"  # 待車主確認
    CONFIRMED = "confirmed"                  # 已確認
    IN_PROGRESS = "in_progress"              # 施工中
    COMPLETED = "completed"                  # 已完工


class Choice:  # 車主對每一項的選擇
    TODAY = "today"
    DEFER = "defer"


class WorkStatus:  # 單項施工狀態
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


# ---------- 車型與零件 ----------

class VehicleModel(Base):
    __tablename__ = "vehicle_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))          # RAV4 2.5 Hybrid GR Sport 4WD
    year: Mapped[int] = mapped_column(Integer)
    powertrain: Mapped[str] = mapped_column(String(50))     # 2.5 油電
    drivetrain: Mapped[str] = mapped_column(String(50))     # E-Four 4WD
    image_url: Mapped[str | None] = mapped_column(String(255))

    parts: Mapped[list["ModelPart"]] = relationship(back_populates="model")


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_no: Mapped[str] = mapped_column(String(30), unique=True)
    name_zh: Mapped[str] = mapped_column(String(50))
    image_url: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(30))
    rule_type: Mapped[str] = mapped_column(String(20))       # RuleType

    # 量測門檻型用
    unit: Mapped[str | None] = mapped_column(String(10))     # mm、%
    safe_min: Mapped[float | None] = mapped_column(Float)    # 低於此值 → 立即處理
    warn_min: Mapped[float | None] = mapped_column(Float)    # 低於此值 → 可延後

    # 里程／時間型用
    interval_km: Mapped[int | None] = mapped_column(Integer)
    interval_months: Mapped[int | None] = mapped_column(Integer)
    warn_km: Mapped[int | None] = mapped_column(Integer)     # 剩餘 ≤ 此值 → 可延後

    safety_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    part_price: Mapped[int] = mapped_column(Integer, default=0)    # NT$
    labor_price: Mapped[int] = mapped_column(Integer, default=0)   # NT$
    labor_minutes: Mapped[int] = mapped_column(Integer, default=0)
    explain_text: Mapped[str] = mapped_column(Text, default="")
    defer_impact_text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(100), default="")
    defer_months: Mapped[int] = mapped_column(Integer, default=3)  # 量測／判定型延後時的建議複查月數


class ModelPart(Base):
    """車型適用哪些零件，以及技師檢查頁的排列順序。"""
    __tablename__ = "model_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("vehicle_models.id"))
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    model: Mapped[VehicleModel] = relationship(back_populates="parts")
    part: Mapped[Part] = relationship()


# ---------- 車輛與保養紀錄 ----------

class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str] = mapped_column(String(20), unique=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("vehicle_models.id"))
    owner_name: Mapped[str] = mapped_column(String(50))
    owner_phone: Mapped[str] = mapped_column(String(20))
    delivered_on: Mapped[date] = mapped_column(Date)   # 交車日（交車時 0 km）

    model: Mapped[VehicleModel] = relationship()
    history: Mapped[list["ServiceHistory"]] = relationship(back_populates="vehicle")


class ServiceHistory(Base):
    __tablename__ = "service_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))
    replaced_on: Mapped[date] = mapped_column(Date)
    replaced_km: Mapped[int] = mapped_column(Integer)

    vehicle: Mapped[Vehicle] = relationship(back_populates="history")
    part: Mapped[Part] = relationship()


# ---------- 工單 ----------

class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    current_km: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default=WorkOrderStatus.CREATED)
    qr_token: Mapped[str] = mapped_column(String(64), unique=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    rule_version: Mapped[str | None] = mapped_column(String(30))
    eta: Mapped[datetime | None] = mapped_column(DateTime)
    brief: Mapped[str | None] = mapped_column(Text)           # 給專員的 30 秒說明稿

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    vehicle: Mapped[Vehicle] = relationship()
    items: Mapped[list["InspectionItem"]] = relationship(back_populates="work_order")
    events: Mapped[list["Event"]] = relationship(back_populates="work_order")


class InspectionItem(Base):
    __tablename__ = "inspection_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"))
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))

    # 技師輸入
    measured_value: Mapped[float | None] = mapped_column(Float)
    tech_status: Mapped[str | None] = mapped_column(String(20))   # TechStatus
    reason: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)  # 技師檢查完這一項的時間

    # 規則引擎輸出
    level: Mapped[str | None] = mapped_column(String(20))         # Level
    remaining_km: Mapped[int | None] = mapped_column(Integer)
    remaining_months: Mapped[int | None] = mapped_column(Integer)
    basis: Mapped[str | None] = mapped_column(Text)               # 判斷依據（一句話）
    price: Mapped[int | None] = mapped_column(Integer)            # 送出時的價格快照

    # 車主選擇與施工
    customer_choice: Mapped[str | None] = mapped_column(String(20))  # Choice
    work_status: Mapped[str] = mapped_column(String(20), default=WorkStatus.PENDING)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)

    work_order: Mapped[WorkOrder] = relationship(back_populates="items")
    part: Mapped[Part] = relationship()
    photos: Mapped[list["Photo"]] = relationship(back_populates="item")


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inspection_items.id"))
    file_path: Mapped[str] = mapped_column(String(255))
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    item: Mapped[InspectionItem] = relationship(back_populates="photos")


# ---------- 時間軸、對話、轉接 ----------

class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"))
    type: Mapped[str] = mapped_column(String(30))   # status_changed、item_done、handoff…
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    work_order: Mapped[WorkOrder] = relationship(back_populates="events")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"))
    role: Mapped[str] = mapped_column(String(20))   # customer、agent、staff
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class HandoffRequest(Base):
    __tablename__ = "handoff_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"))
    status: Mapped[str] = mapped_column(String(20), default="waiting")  # waiting、handling、closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Reminder(Base):
    """交車後的回廠提醒（延後的項目）。"""
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))
    due_date: Mapped[date] = mapped_column(Date)
    due_km: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)        # LINE 推播文字（示意）
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    vehicle: Mapped[Vehicle] = relationship()
    part: Mapped[Part] = relationship()


class Meta(Base):
    """資料表版本。程式更新後版本不同，啟動時會自動重建模擬資料。"""
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
