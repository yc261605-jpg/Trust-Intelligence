# Trust Intelligence MVP

TOYOTA 售後服務 AI 體驗層的可操作原型（2026 和泰 AI 黑客松｜牛來 Team）。

> 競賽概念原型，非 TOYOTA 官方產品或介面；料號、價格、門檻、里程皆為示意。

## 使用者旅程

| 角色 | 做什麼 | 在哪裡 |
| --- | --- | --- |
| 接待 | 輸入車牌建單 → 列印專屬 QR 卡交給車主 | 管理平台 `/a/` |
| 車主 | 掃 QR → 確認車牌 → 看檢查進度與保養紀錄、先問 AI | 手機 `/c/` |
| 技師 | 開始檢查 → 輸入公里數（里程項目自動算）→ 量測 5 項、目視 2 項，一項一張卡 → 送出 | 平板 `/t/` |
| 專員 | 收到「說明稿已備好」→ 照 AI 產生的 30 秒說明稿向車主說明 | 管理平台 `/a/` |
| 車主 | 決策卡先看結論（必須處理／由你決定／今天不用換）→「只換必要的」或「建議的都換」→ 送出 | 手機 |
| 技師 | 收到通知 → 逐項開始／完成 → 品檢完成 | 平板 |
| 車主 | 施工進度與預估完成時間 → 交車摘要＋延後項目回廠提醒（LINE 預覽） | 手機 |

車主有疑問時，每一項都有「問 AI 這一項」；需要真人時一鍵轉接，專員在管理平台「轉接中心」回覆。

## 快速開始（Windows）

只需要先安裝 [Python 3.10+](https://www.python.org/downloads/)（安裝時勾選「Add Python to PATH」）。

1. 下載或 `git clone` 這個專案
2. **雙擊 `start.bat`**：第一次會自動建立虛擬環境、安裝套件、建立 `.env`，接著啟動伺服器並打開管理平台
3. 員工密碼（技師端、管理平台）：`toyota-demo`

> 資料庫不用手動建立，啟動時會自動放入模擬資料。不填 Gemini 金鑰也能完整操作（AI 改用內建規則回答）。

<details>
<summary>手動安裝（macOS／Linux 或想自己下指令）</summary>

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS／Linux：source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # macOS／Linux：cp .env.example .env
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

</details>

## 設定 Gemini

1. 到 Google AI Studio 申請 API Key
2. 打開 `.env`，填入 `GEMINI_API_KEY=你的金鑰`（模型預設 `gemini-3.5-flash-lite`）
3. 重新啟動後端，管理平台右上角會顯示「AI：gemini-3.5-flash-lite」

沒填金鑰或連不上時，AI 服務專員與專員說明稿會自動改用內建的規則式回答，Demo 不會中斷。

## 啟動

最簡單：雙擊專案資料夾裡的 `start.bat`。或在終端機輸入：

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

- 電腦開 http://localhost:8000
- 員工密碼（技師端、管理平台）：`toyota-demo`
- **一定要加 `--host 0.0.0.0`**，少了它伺服器只聽本機，手機掃 QR 一定連不上。

### 手機掃 QR 連不上

管理平台「接待建單」頁下方有「手機連線檢查」，會直接告訴你問題在哪：

1. **顯示「伺服器沒有對區網開放」**：沒加 `--host 0.0.0.0`，改用 `start.bat` 重新啟動。
2. **偵測到多個網路**：電腦有 VPN、WSL、Docker 等虛擬網卡時，自動偵測可能選錯（常是 172.x 開頭）。直接點手機連的那個 Wi-Fi 的 IP（通常是 192.168.x.x），之後產生的 QR 就會用它（已經印出的 QR 請按「重新產生」）。
3. **檢查都正常但手機打不開**：多半是 Windows 防火牆。在 `開放防火牆.bat` 上按右鍵 →「以系統管理員身分執行」；Wi-Fi 若被設成「公用網路」，到 設定 → 網路和網際網路 → Wi-Fi，把網路設定檔類型改成「私人網路」。
4. 手機和電腦要在同一個 Wi-Fi，不要用訪客網路，也不要開行動數據。可以先用手機瀏覽器直接打開檢查頁上顯示的網址 `/c/`，打得開再掃 QR。
5. 朋友不在同一個網路：用 cloudflared 產生公開網址（見下方）。

### 給不在同一個網路的朋友測試（cloudflared）

1. 先用 `start.bat` 啟動伺服器，**另開一個**終端機視窗執行：
   ```powershell
   cloudflared tunnel --url http://localhost:8000
   ```
2. 畫面會出現一行 `https://xxxx-xxxx.trycloudflare.com`。**用這個網址打開管理平台**（`https://xxxx.trycloudflare.com/a/`）再建單，QR 會自動用這個網址，不用改 `.env`。
3. 測試期間兩個視窗都不能關。cloudflared 一關掉或重開，舊網址就失效，手機會出現 `DNS_PROBE_FINISHED_NXDOMAIN`；這時重新執行 cloudflared、用新網址打開管理平台，再按「重新產生」QR。
4. `.env` 的 `PUBLIC_BASE_URL` 請保持空白；如果填過舊的 trycloudflare 網址，清空後重啟伺服器。

## Demo 腳本（ABC-1234 王先生，31,200 km）

1. 管理平台 → 接待建單 → 輸入 `ABC-1234` → 用手機掃畫面上的 QR → 輸入車牌 `ABC-1234`
2. 技師端 → 點工單 → 開始檢查 → 公里數 `31200`
3. 依序檢查（輸入完按「完成，下一項」）：

| 項目 | 輸入 | 結果 |
| --- | --- | --- |
| 前輪煞車來令片 | 3.6 | 可延後 |
| 後輪煞車來令片 | 5.0 | 正常 |
| 前輪胎 | 1.4，拍照，點「胎紋低於法規」 | **必須處理** |
| 後輪胎 | 3.5 | 正常 |
| 12V 電瓶 | 82 | 正常 |
| 前雨刷 | 建議更換，點「膠條硬化」 | 可延後 |
| 油電電池冷卻進風濾網 | 正常 | 正常 |

4. 送出給車主 → 車主手機跳出決策卡；管理平台「工單與說明稿」出現專員說明稿
5. 車主點前輪胎的「問 AI 這一項」→「前輪胎今天不換會怎樣？」→ 選「只換必要的」→ 確認送出
6. 技師端逐項開始／完成 → 品檢完成
7. 車主手機看交車摘要與回廠提醒；管理平台「回廠提醒」列出排程

另外兩台：`BCD-5678`（19,800 km，電瓶填 60 會變可延後）、`CDE-9012`（9,950 km，幾乎全部今天不用換）。數值見 `backend/seed_data.py`。重來：管理平台 → 示範工具 → 重設示範資料。

## 圖片

所有圖片都是 AI 生成（FLUX），不是 TOYOTA 官方素材，車輛沒有任何品牌標誌。正式展示時請標註「概念示意｜AI 生成影像」。

| 位置 | 用途 |
| --- | --- |
| `frontend/static/img/hero_service_bay.jpg` | 車主端愛車主視覺 |
| `frontend/static/img/lounge.jpg` | 首頁客休室情境 |
| `frontend/static/img/delivery.jpg` | 車主端「保養完成」交車頁主視覺 |
| `frontend/static/parts/TI-P001～014.jpg` | 14 個零件圖（決策卡、技師端） |
| `demo_photos/` | 技師檢查照片 8 張，Demo 時在技師端按「拍照」選這些檔案上傳 |

Demo 時技師端各項目建議上傳的照片：前輪煞車來令片 → `前輪煞車來令片_量測.jpg`；前輪胎 → `前輪胎_胎紋量測.jpg`、`前輪胎_左前.jpg`、`前輪胎_右前.jpg`；後輪胎 → `後輪胎_胎紋量測.jpg`；12V 電瓶 → `12V電瓶_檢測.jpg`；前雨刷 → `前雨刷_膠條.jpg`；油電電池冷卻進風濾網 → `油電電池冷卻進風濾網.jpg`。

### TOYOTA 標誌

程式不內建 TOYOTA 標誌。請把黑客松主辦提供的官方標誌檔命名為 `toyota-logo.svg`（或 `toyota-logo.png`），放到 `frontend/static/img/`。三個端的頂部列會自動顯示，不用改程式；沒有檔案時只顯示「Trust Intelligence」文字。深色玻璃列上建議用白色或紅色版本的標誌。

## 架構

```
backend/
  main.py          FastAPI 入口；啟動時檢查資料表版本
  api_admin.py     管理平台：建單與 QR、說明稿、轉接、回廠提醒、零件規則
  api_tech.py      技師端：開始檢查、公里數、逐項存檔、照片、送出、施工
  api_customer.py  車主端：QR 預覽、確認車牌、等待頁、決策、對話、轉接、交車摘要
  services.py      工單流轉、檢查進度、預估完成時間、回廠提醒
  rules.py         規則引擎（量測門檻／里程時間／技師判定 → 三級分級）
  agent.py         AI 服務專員（Gemini 工具呼叫＋Answer Verifier＋規則式備援）與專員說明稿
  models.py        資料表（含資料表版本）
  seed_data.py     模擬資料（14 個零件、3 台示範車）
frontend/          三個前端（純 HTML＋JavaScript）
tests/             規則引擎、完整流程、Gemini 工具呼叫（假伺服器）測試
```

安全設計：分級只由規則引擎決定；AI 只能透過白名單工具查「這張工單」；回答若說必須處理的項目可以延後，Verifier 會整段換成安全回覆。

## 測試

```powershell
python -m pytest -q
```
