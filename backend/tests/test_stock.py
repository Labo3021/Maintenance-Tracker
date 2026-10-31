import io
import zipfile
from datetime import date, timedelta

from openpyxl import Workbook

from api.importer import parse_groups, parse_quantity
from api.scheduling import sync_tasks
from api.schemas import Asset, MaintenanceSchedule

TODAY = date.today()
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def spanish_inventory() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BASE"
    ws.append(["CODIGO", "NOMBRE", "CÓDIGO DEL KIT", "NOMBRE DEL KIT", "CANTIDAD TOTAL SUPUESTA",
               "CANTIDAD TOTAL REAL", "ESTANTE(S)", "NOTA"])
    ws.append(["90001.00", "Trípode variable", 1.88, "KIT PRUEBA A, KIT PRUEBA B", 18, 18, "1,2,3", None])
    ws.append(["90002.00", "Varilla, l = 600 mm", 2.88, "KIT PRUEBA A", 36, 28, "1,2", None])
    ws.append(["90003.20", "Soporte para dinamómetros", 3.88, "KIT PRUEBA A", 12, "10.0", 1, "Caucho seco"])
    ws.append(["90004.00", "Polea", 4.88, 0, 6, 0, "Armario B", None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def import_xlsx(client, **params):
    r = client.post("/api/assets/import", params={"use_ai": False, **params},
                    files={"file": ("BUSCADOR.xlsx", spanish_inventory())})
    assert r.status_code == 200, r.text
    return r.json()


def by_code(client):
    return {a["code"]: a for a in client.get("/api/assets").json() if a.get("code")}


def test_spanish_headers_map_without_ai(client):
    body = import_xlsx(client, dry_run=True)
    fields = {c["header"]: c["field"] for c in body["columns"]}
    assert fields == {
        "CODIGO": "code", "NOMBRE": "name", "CÓDIGO DEL KIT": None, "NOMBRE DEL KIT": "groups",
        "CANTIDAD TOTAL SUPUESTA": "quantity_expected", "CANTIDAD TOTAL REAL": "quantity_actual",
        "ESTANTE(S)": "location", "NOTA": "notes",
    }
    rows = body["preview"]
    assert rows[0]["groups"] == ["KIT PRUEBA A", "KIT PRUEBA B"]
    assert rows[0]["location"] == "Estante 1,2,3"
    assert rows[2]["quantity_actual"] == 10 and rows[2]["notes"] == "Caucho seco"
    assert rows[3]["groups"] == [] and rows[3]["location"] == "Armario B"
    assert body["stock_mismatches"] == 3
    assert body["kits_created"] == 2
    assert body["created"] == 6  # 4 items + 2 kits


def test_stock_tasks_and_kits(client):
    import_xlsx(client, mode="replace")
    assets = by_code(client)
    assert assets["90002.00"]["quantity_missing"] == 8
    tasks = {t["title"]: t for t in client.get("/api/tasks").json() if t["kind"] == "stock"}
    assert set(tasks) == {"Missing 8 units: Varilla, l = 600 mm", "Missing 2 units: Soporte para dinamómetros",
                          "Missing 6 units: Polea"}
    assert tasks["Missing 6 units: Polea"]["priority"] == "high"  # none left at all
    assert tasks["Missing 8 units: Varilla, l = 600 mm"]["due_date"] == TODAY.isoformat()

    kit = assets["kit:kit-prueba-a"]
    assert kit["category"] == "kit" and "3 item types" in kit["notes"] and "10 units missing" in kit["notes"]
    sched = kit["schedules"][0]
    assert sched["title"] == "Physical stock count" and sched["last_done"] == TODAY.isoformat()
    assert sched["next_due"] == (TODAY + timedelta(days=180)).isoformat()


def test_resolving_stock(client):
    import_xlsx(client, mode="replace")
    rod = by_code(client)["90002.00"]
    task = next(t for t in client.get("/api/tasks", params={"asset_id": rod["id"]}).json() if t["kind"] == "stock")
    client.post(f"/api/tasks/{task['id']}/complete", json={"notes": "found in drawer"})
    rod = by_code(client)["90002.00"]
    assert rod["quantity_actual"] == 36 and rod["quantity_missing"] == 0
    assert not [t for t in client.get("/api/tasks", params={"asset_id": rod["id"]}).json() if t["kind"] == "stock"]

    # Updating the count by hand also clears (or changes) the task.
    stand = by_code(client)["90003.20"]
    client.patch(f"/api/assets/{stand['id']}", json={"quantity_actual": 11})
    titles = [t["title"] for t in client.get("/api/tasks", params={"asset_id": stand["id"]}).json()]
    assert titles == ["Missing 1 unit: Soporte para dinamómetros"]
    client.patch(f"/api/assets/{stand['id']}", json={"quantity_actual": 12})
    assert client.get("/api/tasks", params={"asset_id": stand["id"]}).json() == []


def test_reimport_matches_by_code(client):
    import_xlsx(client, mode="replace")
    total = len(client.get("/api/assets").json())
    body = import_xlsx(client)
    assert (body["created"], body["updated"]) == (0, total)
    assert len(client.get("/api/assets").json()) == total


def test_photo_zip_import(client):
    import_xlsx(client, mode="replace")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("imagenes/90001.00.png", PNG)
        z.writestr("imagenes/90001.00.jpg", JPG)   # .jpg preferred over .png
        z.writestr("imagenes/90003-20.jpg", JPG)   # dash vs dot still matches 90003.20
        z.writestr("imagenes/ERROR.png", PNG)
        z.writestr("notes.txt", b"ignored")
    r = client.post("/api/assets/photos/import", files={"file": ("imgs.zip", buf.getvalue(), "application/zip")})
    body = r.json()
    assert body["matched"] == 2 and body["unmatched_files"] == ["ERROR.png"]
    tripod = by_code(client)["90001.00"]
    photo = client.get(tripod["photo_url"])
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    assert client.post("/api/assets/photos/import", files={"file": ("x.zip", b"nope")}).status_code == 422


def test_single_photo_upload(client):
    asset = client.post("/api/assets", json={"name": "Balanza"}).json()
    assert asset["photo_url"] is None
    assert client.get(f"/api/assets/{asset['id']}/photo").status_code == 404
    r = client.put(f"/api/assets/{asset['id']}/photo", files={"image": ("b.png", PNG, "image/png")})
    assert r.json()["photo_url"] == f"/api/assets/{asset['id']}/photo"
    assert client.get(r.json()["photo_url"]).content == PNG


def test_due_now_tasks_stay_put_and_go_overdue():
    """Regression: tasks with no 'last done' date used to be re-dated to today on every sync."""
    asset = Asset(id="a1", name="Freezer", schedules=[MaintenanceSchedule(title="Defrost", interval_days=180)])
    sync_tasks(asset)
    asset.tasks[0].due_date = TODAY - timedelta(days=5)  # created 5 days ago
    sync_tasks(asset)
    assert asset.tasks[0].due_date == TODAY - timedelta(days=5)


def test_parsers():
    assert parse_quantity("10.0") == 10 and parse_quantity("12 u") == 12 and parse_quantity(7.0) == 7
    assert parse_groups("KIT X, EST / COMPLETO; KIT X") == ["KIT X", "EST / COMPLETO"]
    assert parse_groups(0) == [] and parse_groups("N/A") == []
