@echo off
chcp 65001 >nul
net session >/dev/null 2>&1
if errorlevel 1 (
  echo 請在這個檔案上按右鍵，選「以系統管理員身分執行」
  pause
  exit /b
)
netsh advfirewall firewall delete rule name="Trust Intelligence 8000" >/dev/null 2>&1
netsh advfirewall firewall add rule name="Trust Intelligence 8000" dir=in action=allow protocol=TCP localport=8000 profile=private,domain
echo.
echo 已開放 8000 埠（私人網路）。
echo 如果 Wi-Fi 被設成「公用網路」，請到 設定 ^> 網路和網際網路 ^> Wi-Fi ^> 網路設定檔類型，改成「私人網路」。
pause
