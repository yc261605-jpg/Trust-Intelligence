"""讀取 .env 設定。其他檔案一律從這裡拿設定值，不直接讀環境變數。"""
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# 專案根目錄（toyota/）
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
# PUBLIC_BASE_URL 以 .env 為準：避免 PowerShell 裡殘留的舊 trycloudflare 網址蓋過 .env
_file_env = dotenv_values(ROOT_DIR / ".env")
if "PUBLIC_BASE_URL" in _file_env:
    os.environ["PUBLIC_BASE_URL"] = _file_env["PUBLIC_BASE_URL"] or ""


def _sqlite_url(url: str) -> str:
    """把相對路徑的 sqlite 網址換成以專案根目錄為基準的絕對路徑。"""
    prefix = "sqlite:///"
    if url.startswith(prefix) and not Path(url[len(prefix):]).is_absolute():
        db_path = ROOT_DIR / url[len(prefix):]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return prefix + db_path.as_posix()
    return url


class Settings:
    database_url: str = _sqlite_url(os.getenv("DATABASE_URL", "sqlite:///data/trust.db"))
    rule_version: str = os.getenv("RULE_VERSION", "R-2026.11")
    staff_password: str = os.getenv("STAFF_PASSWORD", "toyota-demo")
    secret_key: str = os.getenv("SECRET_KEY", "change-me-demo-secret")
    # 手機掃 QR 要連得到的網址，例如 http://192.168.1.20:8000；留空會自動用電腦的區網 IP
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    upload_dir: Path = ROOT_DIR / "uploads"
    frontend_dir: Path = ROOT_DIR / "frontend"

    # AI 服務專員：Gemini API（OpenAI 相容介面）
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    gemini_base_url: str = os.getenv("GEMINI_BASE_URL",
                                     "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "30"))


settings = Settings()
