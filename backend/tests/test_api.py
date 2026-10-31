from ai import diagnose as diagnose_module
from ai import gemma_client
from config import settings

from conftest import make_pdf

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # content isn't inspected in mock mode


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ai_provider"] == "mock"


def test_assets_seeded_with_computed_dates(client):
    assets = client.get("/api/assets").json()
    assert len(assets) >= 5
    centrifuge = next(a for a in assets if a["id"] == "asset-centrifuge-01")
    assert centrifuge["next_service_due"] == "2026-11-06"
    assert centrifuge["parts"][0]["replace_by"] == "2026-11-01"


def test_asset_crud(client):
    r = client.post("/api/assets", json={"name": "Fume Hood", "category": "fume_hood", "service_interval_days": 90,
                                         "last_service_date": "2026-10-01"})
    assert r.status_code == 201
    asset = r.json()
    assert asset["next_service_due"] == "2026-12-30"

    r = client.patch(f"/api/assets/{asset['id']}", json={"status": "needs_attention"})
    assert r.json()["status"] == "needs_attention"
    assert r.json()["name"] == "Fume Hood"

    assert client.get("/api/assets", params={"category": "fume_hood"}).json()[0]["id"] == asset["id"]
    assert client.delete(f"/api/assets/{asset['id']}").status_code == 204
    assert client.get(f"/api/assets/{asset['id']}").status_code == 404


def test_tasks(client):
    r = client.post("/api/assets/asset-hplc-01/tasks",
                    json={"title": "Replace pump seals", "due_date": "2026-11-20", "priority": "medium"})
    assert r.status_code == 201
    task = r.json()
    r = client.patch(f"/api/assets/asset-hplc-01/tasks/{task['id']}", json={"status": "done"})
    assert r.json()["status"] == "done"


def test_alerts_sorted_and_include_overdue(client):
    alerts = client.get("/api/alerts", params={"within_days": 30}).json()
    days = [a["days_until_due"] for a in alerts]
    assert days == sorted(days)
    assert any(a["days_until_due"] < 0 for a in alerts)


def test_diagnose_mock_creates_task(client):
    r = client.post("/api/diagnose", files={"image": ("gasket.png", PNG, "image/png")},
                    data={"asset_id": "asset-centrifuge-01", "notes": "lid seal looks cracked"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "mock"
    assert body["diagnosis"]["severity"] == "high"
    assert body["task"]["source"] == "diagnosis"
    asset = client.get("/api/assets/asset-centrifuge-01").json()
    assert asset["status"] == "needs_attention"
    assert any(t["id"] == body["task"]["id"] for t in asset["tasks"])


def test_diagnose_without_asset(client):
    r = client.post("/api/diagnose", files={"image": ("x.png", PNG, "image/png")})
    assert r.status_code == 200
    assert r.json()["task"] is None


def test_diagnose_rejects_bad_input(client):
    assert client.post("/api/diagnose", files={"image": ("x.txt", b"hi", "text/plain")}).status_code == 415
    r = client.post("/api/diagnose", files={"image": ("x.png", PNG, "image/png")}, data={"asset_id": "nope"})
    assert r.status_code == 404


def test_manual_upload_and_query(client):
    r = client.post("/api/manuals", files={"file": ("RC-5000 Manual.pdf", make_pdf("Flush the line weekly"),
                                                   "application/pdf")})
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["id"] == "rc-5000-manual"
    assert info["pages"] == 1
    assert any(m["id"] == info["id"] for m in client.get("/api/manuals").json())

    r = client.post("/api/manual-query", json={"manual_id": info["id"], "question": "How do I flush the line?"})
    assert r.status_code == 200
    assert r.json()["source"] == "mock"

    assert client.post("/api/manual-query", json={"manual_id": "missing", "question": "?"}).status_code == 404


def test_diagnosis_retries_then_validates(monkeypatch):
    """Real-provider path: first reply invalid, second valid -> model result."""
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    good = diagnose_module.MOCK_DIAGNOSIS.model_dump()
    replies = iter([{"component": "x"}, good])
    prompts = []

    def fake(prompt, image=None, mime_type="image/jpeg"):
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(gemma_client, "generate_json", fake)
    result, source = diagnose_module.diagnose_image(PNG, "image/png")
    assert source == "model"
    assert result.component == good["component"]
    assert "not valid" in prompts[1]


def test_diagnosis_falls_back_when_model_down(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")

    def boom(*args, **kwargs):
        raise gemma_client.GemmaError("connection refused")

    monkeypatch.setattr(gemma_client, "generate_json", boom)
    result, source = diagnose_module.diagnose_image(PNG, "image/png")
    assert source == "fallback"
    assert result.requires_technician


def test_extract_json_handles_fences():
    assert gemma_client.extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert gemma_client.extract_json('noise {"a": {"b": 2}} trailing') == {"a": {"b": 2}}
