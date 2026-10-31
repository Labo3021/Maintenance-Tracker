#!/usr/bin/env python3
"""Build data/mock_inventory.json, the file the backend seeds from, out of items.json.

Edit items.json, then run this. Don't edit mock_inventory.json by hand.
Uses only the standard library.

    python3 data/scripts/build_inventory.py
"""
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
ITEMS_PATH = DATA_DIR / "items.json"
OUTPUT_PATH = DATA_DIR / "mock_inventory.json"


def to_asset(item):
    manufacturer, _, model = item["itemModel"].partition(" ")
    number = re.fullmatch(r"task_(\d+)", item["id"]).group(1)
    return {
        "id": f"asset-{number}",
        "name": item["title"],
        "category": item["category"].lower(),
        "manufacturer": manufacturer,
        "model": model,
        "location": item["location"],
        "status": "operational",
        "last_service_date": item["installedDate"],
        "service_interval_days": item["replaceEveryDays"],
        # No lifespan here: the service interval already raises the alert for this task.
        "parts": [{"name": item["itemModel"], "installed_date": item["installedDate"]}],
        "tasks": [],
        # The Asset schema ignores these until the fields in backend_fields.patch are added.
        "severity": item["severity"].lower(),
        "difficulty": item["difficulty"].lower(),
        "estimated_minutes": item["estimatedTime"],
        "tools_needed": item["toolsNeeded"],
        "repair_steps": item["repairSteps"],
        "notes": item["notes"],
        "video_url": item["videoURL"],
        "purchase_url": item["purchaseURL"],
        "image_url": "/" + item["imagePath"],
    }


def main():
    items = json.loads(ITEMS_PATH.read_text())
    for item in items:
        image = DATA_DIR / item["imagePath"]
        if not image.is_file():
            raise SystemExit(f"{item['id']}: missing image {image}")
    inventory = {"assets": [to_asset(item) for item in items]}
    OUTPUT_PATH.write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Wrote {len(items)} assets to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
