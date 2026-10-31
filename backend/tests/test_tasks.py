from datetime import date, timedelta

from ai import gemma_client, identify, manual_finder
from config import settings

from conftest import make_pdf

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TODAY = date.today()


def iso(d: date) -> str:
    return d.isoformat()


def onboard(client, last_done: dict[int, date] | None = None, **answers) -> dict:
    """Run the photo -> questions -> save flow the frontend will use."""
    r = client.post("/api/assets/identify", files={"image": ("fridge.jpg", PNG, "image/jpeg")})
    assert r.status_code == 200, r.text
    result = r.json()
    draft = result["draft"]
    for q in result["questions"]:
        target = q["target"]
        if target.startswith("schedules."):
            i = int(target.split(".")[1])
            if last_done and i in last_done:
                draft["schedules"][i]["last_done"] = iso(last_done[i])
        elif target in answers:
            draft[target] = answers[target]
    r = client.post("/api/assets", json=draft)
    assert r.status_code == 201, r.text
    return r.json()


def open_tasks(client, asset_id):
    return client.get("/api/tasks", params={"asset_id": asset_id}).json()


def test_identify_returns_draft_and_questions(client):
    body = client.post("/api/assets/identify", files={"image": ("f.jpg", PNG, "image/jpeg")}).json()
    assert body["source"] == "mock"
    assert body["draft"]["category"] == "refrigerator"
    assert body["draft"]["environment"] == "household"
    targets = [q["target"] for q in body["questions"]]
    assert "manufacturer" not in targets  # brand was read from the photo
    assert "model" in targets and "location" in targets
    assert targets.count("schedules.0.last_done") == 1
    assert len([t for t in targets if t.startswith("schedules.")]) == len(body["draft"]["schedules"])


def test_onboarding_schedules_tasks(client):
    asset = onboard(client, last_done={0: TODAY - timedelta(days=170)}, model="RF28R7351SR", location="Kitchen")
    assert asset["model"] == "RF28R7351SR"
    tasks = {t["title"]: t for t in open_tasks(client, asset["id"])}
    assert len(tasks) == len(asset["schedules"])
    # Filter changed 170 days ago, 180-day interval -> due in 10 days.
    assert tasks["Replace water filter"]["days_until_due"] == 10
    assert tasks["Replace water filter"]["kind"] == "schedule"
    # Unknown last date -> due today.
    assert tasks["Clean condenser coils"]["due_date"] == iso(TODAY)
    assert "No record" in tasks["Clean condenser coils"]["description"]


def test_complete_recurring_task_schedules_next(client):
    asset = onboard(client)
    task = next(t for t in open_tasks(client, asset["id"]) if t["title"] == "Inspect door gaskets")
    done_on = TODAY - timedelta(days=1)
    r = client.post(f"/api/tasks/{task['id']}/complete", json={"completed_on": iso(done_on), "notes": "seal ok"})
    assert r.status_code == 200
    body = r.json()
    assert body["completed"]["status"] == "done" and body["completed"]["notes"] == "seal ok"
    assert body["next_task"]["due_date"] == iso(done_on + timedelta(days=90))
    sched = next(s for s in client.get(f"/api/assets/{asset['id']}").json()["schedules"]
                 if s["title"] == "Inspect door gaskets")
    assert sched["last_done"] == iso(done_on)
    history = client.get("/api/tasks", params={"asset_id": asset["id"], "status": "done"}).json()
    assert [t["id"] for t in history] == [task["id"]]


def test_patch_done_also_rolls_forward(client):
    asset = onboard(client)
    task = open_tasks(client, asset["id"])[0]
    r = client.patch(f"/api/assets/{asset['id']}/tasks/{task['id']}", json={"status": "done"})
    assert r.json()["status"] == "done"
    assert any(t["schedule_id"] == task["schedule_id"] and t["id"] != task["id"]
               for t in open_tasks(client, asset["id"]))


def test_snooze_survives_asset_edits(client):
    asset = onboard(client)
    task = open_tasks(client, asset["id"])[0]
    r = client.post(f"/api/tasks/{task['id']}/snooze", json={"days": 5})
    assert r.json()["due_date"] == iso(TODAY + timedelta(days=5))
    client.patch(f"/api/assets/{asset['id']}", json={"location": "Garage"})
    again = next(t for t in open_tasks(client, asset["id"]) if t["id"] == task["id"])
    assert again["due_date"] == iso(TODAY + timedelta(days=5))


def test_removing_schedule_drops_open_task_keeps_history(client):
    asset = onboard(client)
    first = open_tasks(client, asset["id"])[0]
    client.post(f"/api/tasks/{first['id']}/complete", json={})
    client.patch(f"/api/assets/{asset['id']}", json={"schedules": []})
    assert open_tasks(client, asset["id"]) == []
    done = client.get("/api/tasks", params={"asset_id": asset["id"], "status": "done"}).json()
    assert len(done) == 1


def test_service_interval_task_updates_last_service(client):
    asset = client.post("/api/assets", json={
        "name": "Fume hood", "last_service_date": iso(TODAY - timedelta(days=100)), "service_interval_days": 90,
    }).json()
    task = open_tasks(client, asset["id"])[0]
    assert task["kind"] == "service" and task["days_until_due"] == -10
    client.post(f"/api/tasks/{task['id']}/complete", json={})
    updated = client.get(f"/api/assets/{asset['id']}").json()
    assert updated["last_service_date"] == iso(TODAY)
    assert updated["next_service_due"] == iso(TODAY + timedelta(days=90))


def test_reminders_and_alerts(client):
    asset = client.post("/api/assets", json={"name": "Dryer", "environment": "household", "schedules": [
        {"title": "Clean lint duct", "interval_days": 365, "last_done": iso(TODAY - timedelta(days=363)),
         "priority": "high"},
        {"title": "Wipe drum", "interval_days": 30, "last_done": iso(TODAY)},
    ]}).json()
    titles = [t["title"] for t in client.get("/api/reminders").json() if t["asset_id"] == asset["id"]]
    assert titles == ["Clean lint duct"]  # due in 2 days; "Wipe drum" is 30 days out
    household = client.get("/api/tasks", params={"environment": "household"}).json()
    assert all(t["asset_name"] for t in household)
    alerts = client.get("/api/alerts", params={"within_days": 30}).json()
    assert any(a["title"] == "Wipe drum" and a["kind"] == "schedule" for a in alerts)


def test_calendar_feed(client):
    client.post("/api/assets", json={"name": "Smoke detector, hallway; upstairs", "schedules": [
        {"title": "Test alarm and replace battery if needed", "interval_days": 30, "last_done": iso(TODAY)}]})
    r = client.get("/api/calendar.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    ics = r.text
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == len(client.get("/api/tasks").json())
    assert "TRIGGER:PT9H" in ics and "TRIGGER:-P2DT15H" in ics
    assert "Smoke detector\\, hallway\\; upstairs" in ics.replace("\r\n ", "")
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


def test_find_manual_without_provider(client):
    asset = onboard(client, model="RF28R7351SR")
    r = client.post(f"/api/assets/{asset['id']}/find-manual")
    body = r.json()
    assert body["searched"] is False
    assert "RF28R7351SR" in body["search_url"]
    assert client.get(f"/api/assets/{asset['id']}").json()["manual_search_url"]

    bare = client.post("/api/assets", json={"name": "Mystery box"}).json()
    assert client.post(f"/api/assets/{bare['id']}/find-manual").status_code == 422


def test_find_manual_downloads_and_verifies(client, monkeypatch):
    asset = onboard(client, model="RF28R7351SR")
    monkeypatch.setattr(settings, "search_provider", "brave")
    monkeypatch.setattr(manual_finder, "search", lambda q: [
        {"title": "Fridge forum thread", "url": "https://forum.example.com/t/123"},
        {"title": "Wrong PDF", "url": "https://other.example.com/generic.pdf"},
        {"title": "RF28R7351SR User Manual", "url": "https://www.samsung.com/manuals/RF28R7351SR.pdf"},
    ])
    pdfs = {
        "https://www.samsung.com/manuals/RF28R7351SR.pdf": make_pdf("Model RF28R7351SR water filter"),
        "https://other.example.com/generic.pdf": make_pdf("Some other appliance"),
    }
    monkeypatch.setattr(manual_finder, "download_pdf", lambda url: pdfs.get(url))

    body = client.post(f"/api/assets/{asset['id']}/find-manual").json()
    assert body["searched"] is True
    assert body["candidates"][0]["url"].endswith("RF28R7351SR.pdf")  # PDF + model + maker domain rank first
    assert body["verified"] is True
    saved = client.get(f"/api/assets/{asset['id']}").json()
    assert saved["manual_url"] == body["manual_url"] and saved["manual_id"] == body["manual"]["id"]
    r = client.post("/api/manual-query", json={"manual_id": saved["manual_id"], "question": "filter?"})
    assert r.status_code == 200


def test_manual_link_non_pdf(client, monkeypatch):
    asset = onboard(client)
    monkeypatch.setattr(manual_finder, "download_pdf", lambda url: None)
    body = client.post(f"/api/assets/{asset['id']}/manual-link",
                       json={"url": "https://example.com/support/fridge"}).json()
    assert body["manual"] is None and "isn't a downloadable PDF" in body["message"]
    assert client.get(f"/api/assets/{asset['id']}").json()["manual_url"] == "https://example.com/support/fridge"
    assert client.post(f"/api/assets/{asset['id']}/manual-link", json={"url": "ftp://x"}).status_code == 422


def test_identify_cleans_model_output_and_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    reply = identify.MOCK_ITEM.model_dump() | {"manufacturer": "Unknown", "model": "null", "category": "Washing Machine"}
    monkeypatch.setattr(gemma_client, "generate_json", lambda *a, **k: reply)
    result = identify.identify_image(PNG, "image/png")
    assert result.source == "model"
    assert result.draft.manufacturer is None and result.draft.model is None
    assert result.draft.category == "washing_machine"
    assert result.questions[0].target == "manufacturer"
    assert "door rim" in next(q.hint for q in result.questions if q.target == "model")

    def boom(*a, **k):
        raise gemma_client.GemmaError("down")

    monkeypatch.setattr(gemma_client, "generate_json", boom)
    result = identify.identify_image(PNG, "image/png")
    assert result.source == "fallback" and result.draft.schedules
