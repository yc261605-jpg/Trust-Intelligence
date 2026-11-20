"""FastAPI 入口。

啟動：uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
- 車主端   http://<電腦 IP>:8000/c/
- 技師端   http://<電腦 IP>:8000/t/
- 管理平台 http://<電腦 IP>:8000/a/
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import api_admin, api_customer, api_tech
from .config import settings
from .database import schema_is_current
from .services import FlowError

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """沒有資料庫，或資料表版本和程式不同時，自動重建模擬資料。"""
    if not schema_is_current():
        from .seed import clear_uploads, seed
        print("資料表版本不同，已自動清空並重建模擬資料")
        seed()
        clear_uploads()
    yield


app = FastAPI(title="Trust Intelligence MVP", version="0.1.0", lifespan=lifespan)


@app.exception_handler(FlowError)
async def flow_error_handler(request: Request, exc: FlowError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(api_admin.router)
app.include_router(api_tech.router)
app.include_router(api_customer.router)


@app.get("/api/health")
def health():
    return {"ok": True}


FRONT = settings.frontend_dir
settings.upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")
app.mount("/static", StaticFiles(directory=FRONT / "static"), name="static")
app.mount("/shared", StaticFiles(directory=FRONT / "shared"), name="shared")
app.mount("/c", StaticFiles(directory=FRONT / "customer", html=True), name="customer")
app.mount("/t", StaticFiles(directory=FRONT / "tech", html=True), name="tech")
app.mount("/a", StaticFiles(directory=FRONT / "admin", html=True), name="admin")


@app.get("/")
def index():
    return FileResponse(FRONT / "index.html")
