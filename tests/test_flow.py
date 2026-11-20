"""端到端流程測試：接待建單 → 車主掃 QR 確認車牌 → 技師逐項檢查送出 → 車主決策 → 施工 → 交車＋回廠提醒。"""
from fastapi.testclient import TestClient

from backend import seed_data as D
from backend.agent import verify
from backend.database import SessionLocal
from backend.main import app
from backend.models import Level, WorkOrder

STAFF = {"X-Staff-Key": "test-pass"}


def _create(client, plate):
    r = client.post("/api/admin/work-orders", json={"plate": plate}, headers=STAFF)
    assert r.status_code == 200, r.text
    data = r.json()
    return data["order"]["id"], data["customer_url"].split("t=")[1]


def _login(client, token, plate):
    r = client.post("/api/customer/login", json={"token": token, "plate": plate})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _inspect(client, order_id, plate, submit=True):
    """技師：開始 → 公里數 → 逐項存檔（只做需要動手的項目）→ 送出。"""
    r = client.post(f"/api/tech/work-orders/{order_id}/start", headers=STAFF)
    assert r.status_code == 200, r.text
    r = client.put(f"/api/tech/work-orders/{order_id}/mileage", json={"current_km": D.CURRENT_KM[plate]},
                   headers=STAFF)
    assert r.status_code == 200, r.text
    for it in r.json()["items"]:
        if it["rule_type"] == "mileage":
            assert it["checked"]  # 里程型自動完成
            continue
        value, status, reason = D.SCENARIO_INSPECTIONS[plate][it["part_no"]]
        body = {"measured_value": value, "tech_status": status or it["tech_status"], "reason": reason}
        r2 = client.put(f"/api/tech/items/{it['id']}", json=body, headers=STAFF)
        assert r2.status_code == 200, r2.text
    if submit:
        r = client.post(f"/api/tech/work-orders/{order_id}/submit", headers=STAFF)
        assert r.status_code == 200, r.text


def test_full_flow(fresh_db):
    client = TestClient(app)
    plate = "ABC-1234"
    order_id, token = _create(client, plate)
    assert client.get("/api/tech/work-orders").status_code == 401  # 沒員工密碼不能操作

    # 掃 QR：先看到遮蔽的車牌與車型
    pv = client.get(f"/api/customer/preview?token={token}").json()
    assert pv["plate_hint"] == "ABC-****" and "RAV4" in pv["model"]
    assert client.post("/api/customer/login", json={"token": token, "plate": "XYZ-0000"}).status_code == 401
    cust = _login(client, token, "abc 1234")  # 大小寫、空白、連字號都接受

    # 等待頁：有檢查清單與進度，沒有結果
    wait = client.get("/api/customer/work-order", headers=cust).json()
    assert wait["items"] == [] and len(wait["waiting"]["checklist"]) == 14
    assert wait["waiting"]["visits"][0]["km"] == 20050

    # 技師：還沒檢查完不能送出
    client.post(f"/api/tech/work-orders/{order_id}/start", headers=STAFF)
    r = client.post(f"/api/tech/work-orders/{order_id}/submit", headers=STAFF)
    assert r.status_code == 400
    _inspect(client, order_id, plate, submit=False)

    # 檢查中：車主看到進度前進
    prog = client.get("/api/customer/work-order", headers=cust).json()["progress"]
    assert prog["checked"] == prog["total"] == 7

    # 照片
    first = client.get(f"/api/tech/work-orders/{order_id}", headers=STAFF).json()["items"][0]["id"]
    r = client.post(f"/api/tech/items/{first}/photos", headers=STAFF,
                    files={"file": ("tire.jpg", b"\xff\xd8\xff fake", "image/jpeg")})
    assert r.status_code == 200, r.text

    r = client.post(f"/api/tech/work-orders/{order_id}/submit", headers=STAFF)
    assert r.status_code == 200 and r.json()["brief"]  # 專員說明稿

    # 車主決策卡
    card = client.get("/api/customer/work-order", headers=cust).json()
    assert card["status"] == "awaiting_customer" and "brief" not in card
    levels = {i["part_no"]: i["level"] for i in card["items"]}
    for part_no, want in D.EXPECTED_LEVELS[plate].items():
        assert levels[part_no] == want
    assert card["counts"] == {"immediate": 1, "deferrable": 4, "normal": 9}

    # Agent（備援模式）
    r = client.post("/api/customer/chat", json={"message": "前輪胎今天不換會怎樣？"}, headers=cust).json()
    assert "不提供延後" in r["reply"]
    r = client.post("/api/customer/chat", json={"message": "總共多少錢？"}, headers=cust).json()
    assert "NT$" in r["reply"]

    # 想延後必須處理的項目 → 被拒
    imm = next(i for i in card["items"] if i["level"] == "immediate")
    deferrable = [i for i in card["items"] if i["level"] == "deferrable"]
    choices = {str(i["id"]): "defer" for i in deferrable}
    choices[str(imm["id"])] = "defer"
    assert client.post("/api/customer/decision", json={"choices": choices}, headers=cust).status_code == 400

    choices[str(imm["id"])] = "today"
    oil = next(i for i in deferrable if i["part_no"] == "TI-P001")
    oil_filter = next(i for i in deferrable if i["part_no"] == "TI-P002")
    choices[str(oil["id"])] = choices[str(oil_filter["id"])] = "today"
    r = client.post("/api/customer/decision", json={"choices": choices}, headers=cust)
    assert r.status_code == 200 and r.json()["eta"]

    # 技師施工
    order = client.get(f"/api/tech/work-orders/{order_id}", headers=STAFF).json()
    today = [i for i in order["items"] if i["customer_choice"] == "today"]
    assert len(today) == 3
    assert client.post(f"/api/tech/work-orders/{order_id}/complete", headers=STAFF).status_code == 400
    for it in today:
        assert client.post(f"/api/tech/items/{it['id']}/start", headers=STAFF).status_code == 200
        assert client.post(f"/api/tech/items/{it['id']}/done", headers=STAFF).status_code == 200
    assert client.post(f"/api/tech/work-orders/{order_id}/complete", headers=STAFF).status_code == 200

    # 交車摘要＋回廠提醒
    s = client.get("/api/customer/summary", headers=cust).json()
    assert {i["part_no"] for i in s["done"]} == {"TI-P007", "TI-P001", "TI-P002"}
    assert len(s["deferred"]) == 2 and all(i["reminder"]["due_date"] for i in s["deferred"])
    assert len(s["normal"]) == 9
    assert s["paid_total"] == sum(i["price"] for i in s["done"])
    rem = client.get("/api/admin/reminders", headers=STAFF).json()
    assert len(rem) == 2 and "ABC-1234" in rem[0]["message"]

    # 換過的零件寫回保養紀錄，下一張工單會從新的公里數算起
    order_id2, _ = _create(client, plate)
    _inspect(client, order_id2, plate, submit=False)
    o2 = client.get(f"/api/tech/work-orders/{order_id2}", headers=STAFF).json()
    oil2 = next(i for i in o2["items"] if i["part_no"] == "TI-P001")
    assert oil2["last_km"] == D.CURRENT_KM[plate] and oil2["level"] == "normal"


def test_handoff_and_staff_reply(fresh_db):
    client = TestClient(app)
    order_id, token = _create(client, "CDE-9012")
    cust = _login(client, token, "CDE-9012")
    r = client.post("/api/customer/chat", json={"message": "我想找真人"}, headers=cust).json()
    assert r["suggest_handoff"]
    assert client.post("/api/customer/handoff", headers=cust).status_code == 200
    hs = client.get("/api/admin/handoffs", headers=STAFF).json()
    assert len(hs) == 1 and hs[0]["status"] == "waiting"
    client.post(f"/api/admin/handoffs/{hs[0]['id']}/reply", json={"content": "您好，我是服務專員小林"}, headers=STAFF)
    chat = client.get("/api/customer/chat", headers=cust).json()
    assert chat["handoff_status"] == "handling" and chat["messages"][-1]["role"] == "staff"
    r = client.post("/api/customer/chat", json={"message": "好的謝謝"}, headers=cust).json()
    assert r["reply"] is None and r["handoff_active"]


def test_login_lockout_and_new_qr(fresh_db):
    client = TestClient(app)
    order_id, token = _create(client, "BCD-5678")
    for _ in range(5):
        client.post("/api/customer/login", json={"token": token, "plate": "ZZZ-0000"})
    assert client.post("/api/customer/login", json={"token": token, "plate": "BCD-5678"}).status_code == 423
    r = client.post(f"/api/admin/work-orders/{order_id}/regenerate-qr", headers=STAFF).json()
    new_token = r["customer_url"].split("t=")[1]
    assert client.get(f"/api/customer/preview?token={token}").status_code == 404  # 舊 QR 失效
    _login(client, new_token, "BCD-5678")


def test_verifier_blocks_unsafe_answer(fresh_db):
    client = TestClient(app)
    order_id, token = _create(client, "ABC-1234")
    _inspect(client, order_id, "ABC-1234")
    db = SessionLocal()
    try:
        wo = db.get(WorkOrder, order_id)
        assert any(i.level == Level.IMMEDIATE for i in wo.items)
        assert "不提供延後" in verify("前輪胎其實可以延後，下次再換就好。", wo)
        assert verify("機油可以延後。", wo) == "機油可以延後。"
    finally:
        db.close()


def test_duplicate_order_rejected(fresh_db):
    client = TestClient(app)
    _create(client, "ABC-1234")
    assert client.post("/api/admin/work-orders", json={"plate": "ABC-1234"}, headers=STAFF).status_code == 400
