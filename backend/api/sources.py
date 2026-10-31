"""Private demo data: data/private/<name>/ folders (gitignored), loaded on a fresh start.

Each folder can hold inventory spreadsheets (.xlsx / .csv) and images named by item code
(anywhere inside it, e.g. imagenes/02001.00.jpg). Spreadsheets are imported with the alias
list only (no AI call), so startup stays fast and repeatable.
"""

import logging
from pathlib import Path

from config import settings

from . import importer
from .store import store

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SHEET_EXTS = {".xlsx", ".xlsm", ".csv"}


def load_folder(folder: Path) -> dict:
    summary = {"folder": folder.name, "imported": 0, "skipped_rows": 0, "photos": 0, "errors": []}
    for sheet in sorted(p for p in folder.rglob("*") if p.suffix.lower() in SHEET_EXTS and not p.name.startswith("~$")):
        try:
            result = importer.import_inventory(sheet.name, sheet.read_bytes(), use_ai=False, source=folder.name)
            summary["imported"] += result.created + result.updated
            summary["skipped_rows"] += len(result.skipped)
        except importer.ImportFileError as e:
            summary["errors"].append(f"{sheet.name}: {e}")
    images = [p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS and p.is_file()]
    matched, _ = store.attach_photos_by_code(
        [(p.name, p.stat().st_size, p.read_bytes) for p in images], settings.max_image_bytes
    )
    summary["photos"] = matched
    return summary


def load_private(base: Path) -> list[dict]:
    if not base.is_dir():
        return []
    summaries = [load_folder(folder) for folder in sorted(base.iterdir()) if folder.is_dir()]
    for s in summaries:
        log.info("Private data '%s': %d assets, %d photos, %d rows skipped%s", s["folder"], s["imported"],
                 s["photos"], s["skipped_rows"], f", errors: {s['errors']}" if s["errors"] else "")
    return summaries
