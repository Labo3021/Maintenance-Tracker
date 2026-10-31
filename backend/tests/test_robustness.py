"""Regressions found by the stress test."""

from concurrent.futures import ThreadPoolExecutor


def test_concurrent_writes_and_reads_never_error(client):
    """Readers used to crash with 'dictionary changed size during iteration' during writes."""

    def writer(i):
        a = client.post("/api/assets", json={"name": f"race {i}", "schedules": [{"title": "t", "interval_days": 7}]})
        assert a.status_code == 201
        aid = a.json()["id"]
        task = client.get("/api/tasks", params={"asset_id": aid}).json()[0]
        codes = [client.post(f"/api/tasks/{task['id']}/complete", json={}).status_code]
        if i % 2:
            codes.append(client.delete(f"/api/assets/{aid}").status_code)
        return codes

    def reader(_):
        return [client.get(p).status_code for p in ("/api/tasks?status=all", "/api/alerts", "/api/assets")]

    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda i: writer(i) if i % 2 else reader(i), range(120)))
    assert all(code < 300 for codes in results for code in codes)
    for asset in client.get("/api/assets").json():
        open_keys = [t["schedule_id"] for t in asset["tasks"] if t["status"] == "open" and t["schedule_id"]]
        assert len(open_keys) == len(set(open_keys))


def test_junk_csv_is_a_clear_error_not_500(client):
    r = client.post("/api/assets/import", params={"use_ai": False, "dry_run": True},
                    files={"file": ("x.csv", bytes(range(256)) * 50, "text/csv")})
    assert r.status_code == 422 and r.json()["detail"]


def test_csv_with_line_breaks_inside_quoted_cells(client):
    csv_text = 'Name,Notes\r\n"Fume hood","line one\r\nline two"\r\n'
    body = client.post("/api/assets/import", params={"use_ai": False, "dry_run": True},
                       files={"file": ("x.csv", csv_text, "text/csv")}).json()
    assert body["total_rows"] == 1 and "line two" in body["preview"][0]["notes"]


def test_text_length_limits(client):
    assert client.post("/api/assets", json={"name": "x" * 201}).status_code == 422
    assert client.post("/api/assets", json={"name": "ok", "notes": "x" * 5001}).status_code == 422
    assert client.post("/api/assets", json={"name": "x" * 200, "notes": "x" * 5000}).status_code == 201
