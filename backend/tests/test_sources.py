import json
from datetime import date

from api import sources
from api.store import InventoryStore

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
HOUSEHOLD = {
    "id": "asset-202", "name": "Smoke Detector Battery", "category": "safety", "manufacturer": "Energizer",
    "model": "MAX 9V E522", "last_service_date": "2026-01-10", "service_interval_days": 365, "severity": "high",
    "difficulty": "easy", "estimated_minutes": 2, "tools_needed": ["Step Ladder"],
    "repair_steps": ["Twist the detector off.", "Swap the 9V battery.", "Press Test for 5 s."],
    "video_url": "https://www.youtube.com/watch?v=x", "purchase_url": "https://example.com/b",
    "image_url": "/demo_assets/parts/task_202.jpg",
}


def test_seeds_from_every_source_with_defaults(tmp_path):
    lab = tmp_path / "lab.json"
    lab.write_text(json.dumps({"assets": [{"id": "asset-lab", "name": "Centrifuge"}]}))
    home = tmp_path / "home.json"
    home.write_text(json.dumps({"assets": [HOUSEHOLD, {"id": "asset-lab", "name": "Clash"}]}))
    s = InventoryStore(tmp_path / "storage" / "inventory.json",
                       [(lab, {"environment": "lab"}), (home, {"environment": "household"}), (tmp_path / "missing.json", {})])
    assert s.fresh
    assets = {a.id: a for a in s.list_assets()}
    assert set(assets) == {"asset-lab", "asset-202"} and assets["asset-lab"].name == "Centrifuge"  # first source wins
    smoke = assets["asset-202"]
    assert smoke.environment == "household" and assets["asset-lab"].environment == "lab"
    assert smoke.tools_needed == ["Step Ladder"] and len(smoke.repair_steps) == 3
    assert smoke.photo_url == "/demo_assets/parts/task_202.jpg"  # stock image until a photo is uploaded
    service = next(t for t in smoke.tasks if t.schedule_id == "service")
    assert service.priority == "high"  # inherits the asset's severity

    again = InventoryStore(tmp_path / "storage" / "inventory.json", [(lab, {}), (home, {})])
    assert not again.fresh and len(again.list_assets()) == 2  # saved inventory now; seeds ignored


def test_household_fields_via_api_and_assistant_context(client, monkeypatch):
    from ai import gemma_client
    from config import settings

    asset = client.post("/api/assets", json={k: v for k, v in HOUSEHOLD.items() if k != "id"}).json()
    assert asset["severity"] == "high" and asset["photo_url"] == HOUSEHOLD["image_url"]
    client.put(f"/api/assets/{asset['id']}/photo", files={"image": ("p.png", PNG, "image/png")})
    assert client.get(f"/api/assets/{asset['id']}").json()["photo_url"].startswith("/api/assets/")  # upload wins

    seen = []
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    monkeypatch.setattr(gemma_client, "generate", lambda prompt, **k: seen.append(prompt) or "ok")
    client.post("/api/assistant", json={"equipment_id": asset["id"], "message": "How do I change it?"})
    assert "Step Ladder" in seen[0] and "Swap the 9V battery" in seen[0] and "easy difficulty" in seen[0]
    assert "How-to video" in seen[0] and HOUSEHOLD["video_url"] in seen[0] and HOUSEHOLD["purchase_url"] in seen[0]


def test_demo_assets_are_served(client, tmp_path, monkeypatch):
    r = client.get("/demo_assets/parts/does-not-exist.jpg")
    assert r.status_code == 404  # mounted (no data dir in tests), never a server error


def test_private_folder_loader(client, tmp_path):
    folder = tmp_path / "private" / "school"
    (folder / "imagenes").mkdir(parents=True)
    (folder / "inventario.csv").write_text("CODIGO,NOMBRE,CANTIDAD SUPUESTA,CANTIDAD REAL,KIT\n"
                                           "PRIV-1,Regla,10,7,KIT X\nPRIV-2,Pesa,4,4,KIT X\n", encoding="utf-8")
    (folder / "imagenes" / "PRIV-1.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 20)
    (folder / "imagenes" / "OTHER.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 20)
    (folder / "~$inventario.xlsx").write_bytes(b"excel lock file")  # ignored
    (tmp_path / "private" / "notes.txt").write_text("not a folder; ignored")

    [summary] = sources.load_private(tmp_path / "private")
    assert summary == {"folder": "school", "imported": 3, "skipped_rows": 0, "photos": 1, "errors": []}
    by_code = {a["code"]: a for a in client.get("/api/assets").json() if a.get("code")}
    assert by_code["PRIV-1"]["quantity_missing"] == 3 and by_code["PRIV-1"]["photo_url"]
    assert by_code["kit:kit-x"]["category"] == "kit"
    assert sources.load_private(tmp_path / "nope") == []


def test_source_filter_and_import_source(client):
    csv = "Name,Code\nDrill,SRC-1\nSaw,SRC-2\n"
    r = client.post("/api/assets/import", params={"use_ai": False}, files={"file": ("garage tools.csv", csv, "text/csv")})
    assert r.status_code == 200
    named = client.post("/api/assets/import", params={"use_ai": False, "source": "workshop"},
                        files={"file": ("x.csv", "Name,Code\nVise,SRC-3\n", "text/csv")})
    assert named.status_code == 200
    assert {a["code"] for a in client.get("/api/assets", params={"source": "garage tools"}).json()} == {"SRC-1", "SRC-2"}
    assert [a["code"] for a in client.get("/api/assets", params={"source": "workshop"}).json()] == ["SRC-3"]
    sources = {s["source"]: s["count"] for s in client.get("/api/sources").json()}
    assert sources["garage tools"] == 2 and sources["workshop"] == 1


def test_photo_batch_saves_once(client, monkeypatch):
    from api.store import store
    client.post("/api/assets/import", params={"use_ai": False},
                files={"file": ("b.csv", "Name,Code\nA,BATCH-1\nB,BATCH-2\nC,BATCH-3\n", "text/csv")})
    saves = []
    original = store._save
    monkeypatch.setattr(store, "_save", lambda: saves.append(1) or original())
    files = [(f"BATCH-{i}.jpg", 10, lambda: b"\xff\xd8\xff" + b"0" * 7) for i in (1, 2, 3)]
    assert store.attach_photos_by_code(files, 10_000) == (3, [])
    assert len(saves) == 1
