import io
from datetime import date, datetime

from openpyxl import Workbook

from ai import column_mapper
from api import importer
from api.importer import parse_date, parse_interval, parse_status

MESSY_CSV = """Biology Dept. Equipment List 2019,,,,,,,,
,,,,,,,,
Instrument,Mfr,Model #,S/N,Room,Condition,Last PM,PM Interval (months),Cal Due
Ultra-Low Freezer,ColdCo,ULT-86,ULT-0001,B-12,Working,3/15/2026,6,
Shaking Incubator,ShakeIt,SI-500,SI-777,B-14,needs repair,2026-01-05,12,01/05/2027
,,,,,,,,
,ColdCo,ULT-20,ULT-0002,B-12,OK,13/45/2026,6,
Bad Row Interval,X,Y,BAD-1,B-1,ok,1/1/2026,often,
"""


def post(client, name, content, **params):
    return client.post("/api/assets/import", params=params, files={"file": (name, content, "text/csv")})


def test_messy_csv_dry_run_does_not_save(client):
    before = len(client.get("/api/assets").json())
    r = post(client, "legacy.csv", MESSY_CSV, dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["header_row"] == 3
    fields = {c["header"]: c["field"] for c in body["columns"]}
    assert fields == {
        "Instrument": "name", "Mfr": "manufacturer", "Model #": "model", "S/N": "serial_number",
        "Room": "location", "Condition": "status", "Last PM": "last_service_date",
        "PM Interval (months)": "service_interval_days", "Cal Due": "next_calibration_due",
    }
    assert body["ai_mapping"] == "not_needed"
    assert body["total_rows"] == 4 and body["created"] == 4
    assert len(client.get("/api/assets").json()) == before

    freezer = body["preview"][0]
    assert freezer["status"] == "operational"
    assert freezer["last_service_date"] == "2026-03-15"
    assert freezer["service_interval_days"] == 180
    assert body["preview"][1]["status"] == "needs_attention"
    assert body["preview"][2]["name"] == "ColdCo ULT-20"  # no name -> manufacturer + model

    warnings = " ".join(w["message"] for w in body["warnings"])
    assert "13/45/2026" in warnings and "often" in warnings and "No name" in warnings


def test_csv_import_saves_and_updates_by_serial(client):
    r = post(client, "legacy.csv", MESSY_CSV)
    assert r.json()["created"] == 4
    assets = {a["serial_number"]: a for a in client.get("/api/assets").json()}
    incubator = assets["SI-777"]
    # Due date without a calibration interval becomes a task, not a fake schedule.
    assert any(t["title"] == "Scheduled calibration (imported)" and t["due_date"] == "2027-01-05"
               for t in incubator["tasks"])

    update = "Name,Serial,Status\nShaking Incubator,si-777,broken\n"
    r = post(client, "fix.csv", update)
    assert (r.json()["created"], r.json()["updated"]) == (0, 1)
    incubator = next(a for a in client.get("/api/assets").json() if a["serial_number"] == "SI-777")
    assert incubator["status"] == "out_of_service"
    assert incubator["model"] == "SI-500"  # columns not in the file are kept


def test_xlsx_with_real_dates_and_semicolons(client):
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"
    ws.append(["Lab Inventory"])
    ws.append(["Equipment Name", "Type", "Serial Number", "Last Calibration", "Calibration Frequency", "Parts"])
    ws.append(["Analytical Balance", "Balance", 1290, datetime(2026, 2, 1), "annually",
               "Draft shield | DS-1 | 2026-02-01 | 2 years; Leveling feet"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/assets/import", params={"dry_run": True},
                    files={"file": ("inv.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sheet"] == "Inventory" and body["header_row"] == 2
    a = body["preview"][0]
    assert a["serial_number"] == "1290"  # not "1290.0"
    assert a["category"] == "balance"
    assert a["last_calibration_date"] == "2026-02-01"
    assert a["calibration_interval_days"] == 365
    assert a["parts"][0]["lifespan_days"] == 730 and a["parts"][1]["name"] == "Leveling feet"


def test_ai_maps_unknown_headers(client, monkeypatch):
    seen = {}

    def fake(columns, fields):
        seen.update(columns=columns, fields=fields)
        return {"Gerät": "name", "Kostenstelle": None, "Hersteller": "serial_number"}, "model"

    monkeypatch.setattr(importer, "map_unknown_headers", fake)
    csv_text = "Gerät,Kostenstelle,Hersteller,Model\nZentrifuge,4711,Eppi,5810R\n"
    body = post(client, "de.csv", csv_text, dry_run=True).json()
    methods = {c["header"]: (c["field"], c["method"]) for c in body["columns"]}
    assert methods["Model"] == ("model", "alias")
    assert methods["Gerät"] == ("name", "ai")
    assert methods["Kostenstelle"] == (None, "unmapped")
    assert body["ai_mapping"] == "model"
    assert "model" not in seen["fields"]  # already-matched fields aren't offered to Gemma
    assert seen["columns"]["Gerät"] == ["Zentrifuge"]


def test_ai_disabled_and_bad_files(client):
    body = post(client, "x.csv", "Thing,Model\nA,B\n", dry_run=True, use_ai=False).json()
    assert body["ai_mapping"] == "disabled"
    assert post(client, "x.xls", "whatever").status_code == 422
    assert post(client, "x.csv", "Cost,Owner\n5,Bob\n").status_code == 422
    assert post(client, "x.pdf", "nope").status_code == 422


def test_replace_mode(client):
    post(client, "r.csv", "Name,Serial\nOnly One,ONE-1\n", mode="replace")
    assets = client.get("/api/assets").json()
    assert [a["serial_number"] for a in assets] == ["ONE-1"]


def test_value_parsers():
    assert parse_date("05/10/2026") == date(2026, 5, 10)
    assert parse_date("05/10/2026", "dmy") == date(2026, 10, 5)
    assert parse_date(46000) == date(2025, 12, 9)
    assert parse_date("Mar 3, 2026") == date(2026, 3, 3)
    assert parse_interval("6 months", "") == 180
    assert parse_interval(2, "Interval (years)") == 730
    assert parse_interval("Semi-Annual", "") == 182
    assert parse_interval("every 2 weeks", "") == 14
    assert parse_status("Not working") == "out_of_service"
    assert parse_status("In Service") == "operational"
    assert parse_status("Under maintenance") == "needs_attention"


def test_column_mapper_mock_mode():
    assert column_mapper.map_unknown_headers({"X": ["1"]}, {"name": "n"}) == ({}, "mock")
