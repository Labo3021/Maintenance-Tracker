from datetime import date, timedelta

from ai import agent as agent_module
from ai import gemma_client
from ai.diagnose import MOCK_DIAGNOSIS
from ai.proactive import agent as proactive
from config import settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TODAY = date.today()


def make_stock(client, name, expected, actual, **extra):
    return client.post("/api/assets", json={"name": name, "quantity_expected": expected, "quantity_actual": actual,
                                            "location": "Store room B", **extra}).json()


def scripted(monkeypatch, replies):
    """Real-provider path with a fake model that answers from a script; inspect_image uses MOCK_DIAGNOSIS."""
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    it = iter(replies)
    prompts = []
    monkeypatch.setattr(gemma_client, "generate_json", lambda prompt, **k: prompts.append(prompt) or next(it))
    monkeypatch.setattr(agent_module, "diagnose_image", lambda *a, **k: (MOCK_DIAGNOSIS, "model"))
    return prompts


def test_agent_uses_tools_and_reports_ground_truth(client, monkeypatch):
    centrifuge = client.post("/api/assets", json={"name": "Agent centrifuge", "category": "centrifuge"}).json()
    make_stock(client, "Lid gasket", 4, 3, code="LG-1")
    prompts = scripted(monkeypatch, [
        {"thought": "look first", "tool": "inspect_image", "args": {}},
        {"thought": "need a gasket", "tool": "check_inventory", "args": {"part_name": "Replacement lid gasket (OEM part)"}},
        {"thought": "book it", "tool": "schedule_task", "args": {"title": "Replace lid gasket", "priority": "high", "due_in_days": 1}},
        {"thought": "done", "final": {"summary": "The lid gasket is cracked; replace it.", "safety": ["Unplug first"],
                                      "next_steps": ["Fit the spare gasket"],
                                      "parts": [{"part": "Made-up part", "in_stock": True}]}},
    ])
    r = client.post("/api/agents/diagnose", files={"image": ("p.png", PNG, "image/png")},
                    data={"asset_id": centrifuge["id"], "notes": "aerosol smell"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "agent"
    assert [s["tool"] for s in body["steps"]] == ["inspect_image", "check_inventory", "schedule_task"]
    report = body["report"]
    assert report["summary"] == "The lid gasket is cracked; replace it." and report["severity"] == "high"
    # Parts come from what check_inventory returned, not the model's invented "Made-up part".
    assert [p["match"] for p in report["parts"]] == ["Lid gasket"]
    assert report["parts"][0]["in_stock"] is True and report["parts"][0]["quantity"] == 3
    assert report["actions_taken"][0].startswith("Scheduled 'Replace lid gasket' (high)")
    assert body["task"]["due_date"] == (TODAY + timedelta(days=1)).isoformat()
    assert any(t["id"] == body["task"]["id"] for t in client.get(f"/api/assets/{centrifuge['id']}").json()["tasks"])
    assert "Lid gasket" in prompts[2] and "aerosol smell" in prompts[0]  # tool results feed the next step


def test_agent_falls_back_to_guided_when_model_misbehaves(client, monkeypatch):
    asset = client.post("/api/assets", json={"name": "Guided centrifuge"}).json()
    scripted(monkeypatch, [{"tool": "dance"}, {"tool": "dance"}, {"tool": "dance"}])
    body = client.post("/api/agents/diagnose", files={"image": ("p.png", PNG, "image/png")},
                       data={"asset_id": asset["id"]}).json()
    assert body["mode"] == "guided"
    tools = [s["tool"] for s in body["steps"]]
    assert tools[:2] == ["dance", "dance"] and "inspect_image" in tools and tools[-1] == "schedule_task"
    assert body["report"]["next_steps"]  # filled from the diagnosis


def test_agent_must_inspect_before_finishing_and_never_repeats(client, monkeypatch):
    scripted(monkeypatch, [
        {"final": {"summary": "too early"}},
        {"tool": "check_inventory", "args": {"part_name": "fuse"}},
        {"tool": "check_inventory", "args": {"part_name": "fuse"}},
        {"final": {"summary": "Ok now."}},
    ])
    body = client.post("/api/agents/diagnose", files={"image": ("p.png", PNG, "image/png")}).json()
    tools = [s["tool"] for s in body["steps"]]
    assert tools[0] == "inspect_image"  # forced before the early final
    assert "already called" in body["steps"][2]["result"]
    assert body["report"]["summary"] == "Ok now." and body["task"] is None  # no asset -> nothing scheduled


def test_agent_mock_mode_and_bad_input(client):
    asset = client.post("/api/assets", json={"name": "Mock centrifuge"}).json()
    body = client.post("/api/agents/diagnose", files={"image": ("p.png", PNG, "image/png")},
                       data={"asset_id": asset["id"]}).json()
    assert body["mode"] == "mock" and body["steps"][0]["tool"] == "inspect_image" and body["task"]
    assert client.post("/api/agents/diagnose", files={"image": ("x.txt", b"hi", "text/plain")}).status_code == 415
    assert client.post("/api/agents/diagnose", files={"image": ("p.png", PNG, "image/png")},
                       data={"asset_id": "nope"}).status_code == 404


def test_proactive_agent_finds_due_work_and_drafts_requisitions(client):
    cal = client.post("/api/assets", json={
        "name": "Proactive spectrograph", "last_calibration_date": (TODAY - timedelta(days=176)).isoformat(),
        "calibration_interval_days": 180}).json()
    empty = make_stock(client, "Proactive HEPA filter", 2, 0, source="proactive-test",
                       purchase_url="https://example.com/hepa")
    low = make_stock(client, "Proactive seal", 10, 7, source="proactive-test")

    report = client.post("/api/agents/proactive/run").json()
    assert report["last_run"] and report["summary"] and report["summary_source"] == "mock"
    due = [a for a in report["due_soon"] if a["asset_id"] == cal["id"]]
    assert due and due[0]["kind"] == "calibration" and due[0]["days_until_due"] == 4
    req = next(r for r in report["requisitions"] if r["source"] == "proactive-test")
    lines = {line["asset_id"]: line for line in req["lines"]}
    assert lines[empty["id"]]["quantity"] == 2 and lines[empty["id"]]["reason"].startswith("None left")
    assert lines[empty["id"]]["purchase_url"] == "https://example.com/hepa"
    assert lines[low["id"]]["quantity"] == 3

    again = client.post("/api/agents/proactive/run").json()
    assert sum(1 for r in again["requisitions"] if r["source"] == "proactive-test") == 1  # no duplicates

    r = client.patch(f"/api/agents/requisitions/{req['id']}", json={"status": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.patch("/api/agents/requisitions/nope", json={"status": "approved"}).status_code == 404
    assert client.patch(f"/api/agents/requisitions/{req['id']}", json={"status": "bought"}).status_code == 422
    assert client.get("/api/agents/proactive").json()["requisitions"][0]["id"]


def test_proactive_briefing_uses_model_with_fallback(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    monkeypatch.setattr(gemma_client, "generate", lambda prompt, **k: "Calibrate the spectrograph first.")
    assert client.post("/api/agents/proactive/run").json()["summary_source"] == "model"

    def boom(*a, **k):
        raise gemma_client.GemmaError("down")

    monkeypatch.setattr(gemma_client, "generate", boom)
    body = client.post("/api/agents/proactive/run").json()
    assert body["summary_source"] == "fallback" and "short" in body["summary"]
