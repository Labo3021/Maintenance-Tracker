"""REST routes. Handlers are plain `def` so FastAPI runs slow model calls in a threadpool."""

from typing import Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from ai import manuals
from ai.diagnose import diagnose_image
from config import settings

from . import importer
from .schemas import (
    Alert,
    Asset,
    AssetCreate,
    AssetStatus,
    AssetUpdate,
    DiagnoseResponse,
    ImportMode,
    ImportResult,
    MaintenanceTask,
    ManualAnswer,
    ManualInfo,
    ManualQuery,
    TaskCreate,
    TaskUpdate,
)
from .store import store

router = APIRouter(prefix="/api")

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _asset_or_404(asset_id: str) -> Asset:
    asset = store.get(asset_id)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    return asset


# --- Assets ------------------------------------------------------------------


@router.get("/assets", response_model=list[Asset], tags=["assets"])
def list_assets(category: Optional[str] = None, status: Optional[AssetStatus] = None):
    return store.list_assets(category=category, status=status)


@router.post("/assets", response_model=Asset, status_code=201, tags=["assets"])
def create_asset(body: AssetCreate):
    return store.create(body)


@router.post("/assets/import", response_model=ImportResult, tags=["assets"])
def import_assets(
    file: UploadFile = File(..., description="Inventory spreadsheet: .csv or .xlsx"),
    mode: ImportMode = Query("append", description="append: add/update by serial number. replace: wipe inventory first"),
    dry_run: bool = Query(False, description="Parse and report without saving; use for a preview step"),
    date_order: Literal["mdy", "dmy"] = Query("mdy", description="How to read ambiguous dates like 05/10/2026"),
    use_ai: bool = Query(True, description="Ask Gemma to match column headers the alias list doesn't know"),
    sheet: Optional[str] = Query(None, description="Excel sheet name; defaults to the first sheet"),
):
    """Import a legacy inventory. Rows that can't be parsed are skipped and listed, not fatal."""
    data = file.file.read()
    if not data:
        raise HTTPException(400, "File is empty")
    if len(data) > settings.max_pdf_bytes:
        raise HTTPException(413, "File is too large")
    try:
        return importer.import_inventory(
            file.filename or "inventory.csv", data,
            mode=mode, dry_run=dry_run, date_order=date_order, use_ai=use_ai, sheet=sheet,
        )
    except importer.ImportFileError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/assets/{asset_id}", response_model=Asset, tags=["assets"])
def get_asset(asset_id: str):
    return _asset_or_404(asset_id)


@router.patch("/assets/{asset_id}", response_model=Asset, tags=["assets"])
def update_asset(asset_id: str, body: AssetUpdate):
    asset = store.update(asset_id, body)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    return asset


@router.delete("/assets/{asset_id}", status_code=204, tags=["assets"])
def delete_asset(asset_id: str):
    if not store.delete(asset_id):
        raise HTTPException(404, f"Asset '{asset_id}' not found")


@router.post("/assets/{asset_id}/tasks", response_model=MaintenanceTask, status_code=201, tags=["assets"])
def create_task(asset_id: str, body: TaskCreate):
    _asset_or_404(asset_id)
    return store.add_task(asset_id, body)


@router.patch("/assets/{asset_id}/tasks/{task_id}", response_model=MaintenanceTask, tags=["assets"])
def update_task(asset_id: str, task_id: str, body: TaskUpdate):
    _asset_or_404(asset_id)
    task = store.update_task(asset_id, task_id, body)
    if task is None:
        raise HTTPException(404, f"Task '{task_id}' not found")
    return task


@router.get("/alerts", response_model=list[Alert], tags=["assets"])
def list_alerts(within_days: int = Query(30, ge=0, le=365)):
    """Upcoming and overdue service, calibration, part replacements and open tasks."""
    return store.alerts(within_days)


# --- Diagnose ----------------------------------------------------------------


@router.post("/diagnose", response_model=DiagnoseResponse, tags=["diagnose"])
def diagnose(
    image: UploadFile = File(..., description="JPEG, PNG or WebP photo of the equipment"),
    asset_id: Optional[str] = Form(None, description="If given, the diagnosis is saved as a task on this asset"),
    notes: Optional[str] = Form(None, description="Optional symptoms, e.g. 'loud grinding at high RPM'"),
):
    if image.content_type not in IMAGE_TYPES:
        raise HTTPException(415, f"Unsupported image type '{image.content_type}'. Use JPEG, PNG or WebP.")
    data = image.file.read()
    if not data:
        raise HTTPException(400, "Image is empty")
    if len(data) > settings.max_image_bytes:
        raise HTTPException(413, "Image is too large")

    asset = _asset_or_404(asset_id) if asset_id else None
    hint = " ".join(filter(None, [asset.manufacturer, asset.model, asset.name])) if asset else None

    diagnosis, source = diagnose_image(data, image.content_type, equipment_hint=hint, notes=notes)
    # Don't schedule work from a failed diagnosis; the UI shows the fallback instead.
    task = store.add_task_from_diagnosis(asset.id, diagnosis) if asset and source != "fallback" else None
    return DiagnoseResponse(diagnosis=diagnosis, source=source, task=task)


# --- Manuals -----------------------------------------------------------------


@router.get("/manuals", response_model=list[ManualInfo], tags=["manuals"])
def list_manuals():
    return manuals.list_manuals()


@router.post("/manuals", response_model=ManualInfo, status_code=201, tags=["manuals"])
def upload_manual(file: UploadFile = File(..., description="PDF equipment manual")):
    if file.content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Upload a PDF file")
    data = file.file.read()
    if len(data) > settings.max_pdf_bytes:
        raise HTTPException(413, "PDF is too large")
    try:
        return manuals.save_and_add(file.filename or "manual.pdf", data)
    except manuals.ManualError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/manual-query", response_model=ManualAnswer, tags=["manuals"])
def manual_query(body: ManualQuery):
    manual = manuals.get_manual(body.manual_id)
    if manual is None:
        raise HTTPException(404, f"Manual '{body.manual_id}' not found. Upload it via POST /api/manuals.")
    return manuals.ask(manual, body.question)
