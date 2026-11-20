"""資料庫連線。之後 API 用 get_db() 取得 session。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite 給 FastAPI 多執行緒用
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 的相依注入用：每個請求一個 session，結束後關閉。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SCHEMA_VERSION = "5"


def schema_is_current() -> bool:
    """資料庫存在且版本相同才算最新。"""
    from sqlalchemy import inspect, text
    if not inspect(engine).has_table("meta"):
        return False
    with engine.connect() as conn:
        row = conn.execute(text("SELECT value FROM meta WHERE key = 'schema_version'")).first()
    return bool(row) and row[0] == SCHEMA_VERSION


def reset_db():
    """刪掉所有資料表再重建（只給 seed 用）。"""
    from . import models  # noqa: F401  讓 Base 知道有哪些表

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
