"""Agent 的 Gemini 路徑：用假的 OpenAI 相容伺服器模擬 Gemini 的工具呼叫，不需要真的 API Key。"""
import json

import httpx
from fastapi.testclient import TestClient

from backend import agent
from backend.config import settings
from backend.main import app
from tests.test_flow import STAFF, _create, _inspect, _login


def _fake_gemini(reply_text, brief_text="專員說明稿：前輪胎紋 1.4 mm 今天必須更換。"):
    calls = {"n": 0, "tool_results": [], "bodies": []}

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls["bodies"].append(body)
        assert request.headers["authorization"] == "Bearer fake-key"
        assert body["model"] == settings.gemini_model
        if "tools" not in body:  # 專員說明稿
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": brief_text}}]})
        calls["n"] += 1
        tool_msgs = [m for m in body["messages"] if m["role"] == "tool"]
        if not tool_msgs:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "c1", "type": "function", "extra_content": {"google": {"thought_signature": "sig"}},
                "function": {"name": "get_item_detail", "arguments": json.dumps({"part_name": "前輪胎"})}}]}
        else:
            # thought signature 要原樣送回
            assistant = next(m for m in body["messages"] if m.get("tool_calls"))
            assert assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig"
            calls["tool_results"] = [json.loads(m["content"]) for m in tool_msgs]
            msg = {"role": "assistant", "content": reply_text}
        return httpx.Response(200, json={"choices": [{"message": msg}]})

    return handler, calls


def _setup(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(agent.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    client = TestClient(app)
    order_id, token = _create(client, "ABC-1234")
    _inspect(client, order_id, "ABC-1234")
    return client, _login(client, token, "ABC-1234"), order_id


def test_gemini_tool_calling_and_brief(fresh_db, monkeypatch):
    handler, calls = _fake_gemini("前輪胎紋 1.4 mm，低於法規 1.6 mm，今天必須更換。")
    client, cust, order_id = _setup(monkeypatch, handler)
    # 送出時產生的說明稿來自 Gemini
    order = client.get(f"/api/admin/work-orders/{order_id}", headers=STAFF).json()
    assert order["brief"].startswith("專員說明稿")
    r = client.post("/api/customer/chat", json={"message": "前輪胎為什麼要換？"}, headers=cust).json()
    assert r["engine"] == "llm" and r["reply"].startswith("前輪胎紋 1.4 mm")
    detail = calls["tool_results"][0]["項目"][0]
    assert detail["量測值"] == "1.4 mm" and detail["分級"] == "立即處理"
    # 沒有參數的工具不送 parameters（Gemini 不接受空的 object schema）
    tools = calls["bodies"][-1]["tools"]
    assert "parameters" not in next(t for t in tools if t["function"]["name"] == "get_progress")["function"]


def test_gemini_unsafe_answer_is_replaced(fresh_db, monkeypatch):
    handler, _ = _fake_gemini("前輪胎其實可以延後，下個月再換也沒關係。")
    client, cust, _ = _setup(monkeypatch, handler)
    r = client.post("/api/customer/chat", json={"message": "前輪胎可以晚點換嗎？"}, headers=cust).json()
    assert "不提供延後" in r["reply"]


def test_gemini_down_falls_back(fresh_db, monkeypatch):
    def broken(request):
        raise httpx.ConnectError("網路斷線")
    client, cust, order_id = _setup(monkeypatch, broken)
    order = client.get(f"/api/admin/work-orders/{order_id}", headers=STAFF).json()
    assert "王先生您好" in order["brief"]  # 範本說明稿
    r = client.post("/api/customer/chat", json={"message": "前輪胎為什麼要換？"}, headers=cust).json()
    assert r["engine"] == "fallback" and "1.4" in r["reply"]
