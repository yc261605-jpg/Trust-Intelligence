@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv (
  echo [1/3] 第一次執行：建立虛擬環境，約需 1～2 分鐘...
  python -m venv .venv || (echo 找不到 Python，請先安裝 Python 3.10 以上版本 & pause & exit /b)
)
call .venv\Scripts\activate.bat
echo [2/3] 檢查套件...
pip install -q -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo 已從 .env.example 建立 .env（沒填 GEMINI_API_KEY 也能跑，AI 會改用內建規則回答）
)

echo [3/3] 啟動 Trust Intelligence（對區網開放，手機才連得到）...
echo 電腦開：http://localhost:8000　員工密碼見 .env 的 STAFF_PASSWORD（預設 toyota-demo）
start "" cmd /c "timeout /t 3 >nul & start http://localhost:8000/a/"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
pause
