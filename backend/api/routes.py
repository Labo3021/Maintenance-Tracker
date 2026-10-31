"""REST routes. Handlers are plain `def` so FastAPI runs slow model calls in a threadpool."""

from typing import Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile

from ai import manual_finder, manuals
from ai.diagnose import diagnose_image
from ai.identify import identify_image
from config import settings

from . import importer
from .calendar import build_ics
from .schemas import (
    Alert,
    Asset,
    AssetCreate,
    AssetStatus,
    AssetUpdate,
    DiagnoseResponse,
    Environment,
    FindManualResult,
    IdentifyResult,
    ImportMode,
    ImportResult,
    MaintenanceTask,
    ManualAnswer,
    ManualInfo,
    ManualLinkRequest,
    ManualQuery,
    TaskComplete,
    TaskCompleteResult,
    TaskCreate,
    TaskSnooze,
    TaskUpdate,
    TaskView,
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


def _read_image(image: UploadFile) -> bytes:
    if image.content_type not in IMAGE_TYPES:
        raise HTTPException(415, f"Unsupported image type '{image.content_type}'. Use JPEG, PNG or WebP.")
    data = image.file.read()
    if not data:
        raise HTTPException(400, "Image is empty")
    if len(data) > settings.max_image_bytes:
        raise HTTPException(413, "Image is too large")
    return data


@router.post("/assets/identify", response_model=IdentifyResult, tags=["assets"])
def identify_asset(
    image: UploadFile = File(..., description="Photo of the appliance or equipment"),
    notes: Optional[str] = Form(None, description="Optional context, e.g. 'bought in 2021'"),
):
    """Step 1 of adding equipment from a photo. Nothing is saved: show `questions`, write the
    answers into `draft` at each question's `target`, then POST the draft to /api/assets."""
    return identify_image(_read_image(image), image.content_type, notes=notes)


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


# --- Task manager ------------------------------------------------------------


@router.get("/tasks", response_model=list[TaskView], tags=["tasks"])
def list_tasks(
    status: Literal["open", "done", "all"] = "open",
    within_days: Optional[int] = Query(None, ge=0, le=3650, description="Due within N days (overdue always included)"),
    asset_id: Optional[str] = None,
    environment: Optional[Environment] = None,
):
    """Every task across all equipment, soonest first."""
    return store.list_tasks(
        status=None if status == "all" else status, within_days=within_days, asset_id=asset_id, environment=environment
    )


@router.post("/tasks/{task_id}/complete", response_model=TaskCompleteResult, tags=["tasks"])
def complete_task(task_id: str, body: TaskComplete = TaskComplete()):
    """Mark done. Recurring tasks record the date and return the next occurrence."""
    result = store.complete_task(task_id, body.completed_on, body.notes)
    if result is None:
        raise HTTPException(404, f"Task '{task_id}' not found")
    done, nxt = result
    return TaskCompleteResult(completed=done, next_task=nxt)


@router.post("/tasks/{task_id}/snooze", response_model=MaintenanceTask, tags=["tasks"])
def snooze_task(task_id: str, body: TaskSnooze):
    task = store.snooze_task(task_id, body.days)
    if task is None:
        raise HTTPException(404, f"Task '{task_id}' not found")
    return task


@router.get("/reminders", response_model=list[TaskView], tags=["tasks"])
def reminders(days_before: Optional[int] = Query(None, ge=0, le=60, description="Defaults to REMIND_DAYS_BEFORE")):
    """What to notify the user about now: overdue tasks and tasks due within a few days.
    The frontend can poll this and show browser notifications."""
    return store.reminders(settings.remind_days_before if days_before is None else days_before)


@router.get("/calendar.ics", tags=["tasks"], response_class=Response)
def calendar_feed(environment: Optional[Environment] = None):
    """Open tasks as an iCalendar feed with alarms. Import or subscribe in Google/Apple/Outlook calendar."""
    ics = build_ics(store.list_tasks(status="open", environment=environment))
    return Response(
        ics,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="labguard-tasks.ics"'},
    )


@router.get("/alerts", response_model=list[Alert], tags=["tasks"])
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
    data = _read_image(image)
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


# --- Manual finder -----------------------------------------------------------


@router.post("/assets/{asset_id}/find-manual", response_model=FindManualResult, tags=["manuals"])
def find_manual(asset_id: str, download: bool = Query(True, description="Download and load the best PDF for Q&A")):
    """Search the web for the asset's manual (needs SEARCH_PROVIDER). Always returns a search link;
    saves the best link on the asset and, if a PDF is found, loads it for /api/manual-query."""
    asset = _asset_or_404(asset_id)
    if not (asset.manufacturer or asset.model):
        raise HTTPException(422, "Add the brand or model number first; they're needed to find the manual.")
    query = manual_finder.build_query(asset)
    result = FindManualResult(
        asset_id=asset_id, query=query, search_url=manual_finder.search_url(query), searched=False, message=""
    )
    if settings.search_provider == "none":
        result.message = (
            "Automatic search is off (SEARCH_PROVIDER=none). Open search_url, then save the manual "
            f"with POST /api/assets/{asset_id}/manual-link."
        )
        return result

    try:
        candidates = manual_finder.rank(manual_finder.search(query), asset)
    except manual_finder.SearchError as e:
        result.message = f"{e}. Use search_url instead."
        return result
    result.searched, result.candidates = True, candidates

    if download:
        for c in [c for c in candidates if c.is_pdf][: manual_finder.MAX_DOWNLOAD_TRIES]:
            info, verified = manual_finder.load_from_url(c.url, asset)
            if info and (verified or result.manual is None):
                result.manual, result.verified, result.manual_url = info, verified, c.url
            if verified:
                break
    if result.manual_url is None and candidates:
        result.manual_url = candidates[0].url

    if result.manual_url:
        update = {"manual_url": result.manual_url}
        if result.manual:
            update["manual_id"] = result.manual.id
        store.update(asset_id, AssetUpdate(**update))

    if result.manual and result.verified:
        result.message = "Manual downloaded, matched to the model number, and ready for questions."
    elif result.manual:
        result.message = "A PDF was downloaded but the model number wasn't found inside; double-check it's the right one."
    elif result.manual_url:
        result.message = "No downloadable PDF found; saved the best link instead."
    else:
        result.message = "Nothing found. Try search_url, or check the brand and model."
    return result


@router.post("/assets/{asset_id}/manual-link", response_model=FindManualResult, tags=["manuals"])
def set_manual_link(asset_id: str, body: ManualLinkRequest):
    """Save a manual link the user found. If it's a PDF, download and load it for Q&A."""
    asset = _asset_or_404(asset_id)
    query = manual_finder.build_query(asset)
    result = FindManualResult(
        asset_id=asset_id, query=query, search_url=manual_finder.search_url(query), searched=False,
        manual_url=body.url, message="Link saved.",
    )
    update = {"manual_url": body.url}
    if body.download:
        info, verified = manual_finder.load_from_url(body.url, asset)
        if info:
            result.manual, result.verified = info, verified
            update["manual_id"] = info.id
            result.message = "Link saved and manual loaded for questions."
        else:
            result.message = "Link saved. It isn't a downloadable PDF, so Q&A isn't available for it."
    store.update(asset_id, AssetUpdate(**update))
    return result
