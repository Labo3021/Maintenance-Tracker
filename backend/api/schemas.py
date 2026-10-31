"""Data contracts shared by the API routes, the AI layer, and the frontend.

Change these only with the whole team: the frontend builds against the shapes
shown at http://localhost:8000/docs.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Optional
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, StringConstraints, computed_field

Severity = Literal["low", "medium", "high", "critical"]
AssetStatus = Literal["operational", "needs_attention", "out_of_service"]
TaskStatus = Literal["open", "done"]
ResultSource = Literal["model", "mock", "fallback"]
# Length limits keep one bad request or import row from bloating the data file.
ShortText = Annotated[str, StringConstraints(max_length=200)]
LongText = Annotated[str, StringConstraints(max_length=5000)]
Environment = Literal["lab", "household", "enterprise"]
ScheduleKind = Literal["inspect", "clean", "replace", "service", "calibrate"]
TaskKind = Literal["service", "calibration", "part", "schedule", "stock", "task"]


# --- Diagnosis (Visual Equipment Inspector) ---------------------------------


class SafetyHazard(BaseModel):
    type: str = Field(description="e.g. biohazard, high_voltage, chemical, pressure, thermal, mechanical")
    description: str


class RepairStep(BaseModel):
    step: int = Field(ge=1)
    instruction: str
    caution: Optional[str] = None


class DiagnosisResult(BaseModel):
    """What Gemma must return for a photo. Also used to validate the model's JSON."""

    component: str
    issue: str
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    hazards: list[SafetyHazard] = []
    tools: list[str] = []
    parts_needed: list[str] = []
    steps: list[RepairStep] = []
    requires_technician: bool = False


# --- Inventory & scheduling --------------------------------------------------


class Part(BaseModel):
    name: str
    part_number: Optional[str] = None
    installed_date: Optional[date] = None
    lifespan_days: Optional[int] = Field(default=None, ge=1)

    @computed_field
    @property
    def replace_by(self) -> Optional[date]:
        if self.installed_date and self.lifespan_days:
            return self.installed_date + timedelta(days=self.lifespan_days)
        return None


class MaintenanceSchedule(BaseModel):
    """A recurring job, e.g. "Replace water filter" every 180 days. Keeps one open task alive."""

    id: str = Field(default_factory=lambda: f"sch-{uuid.uuid4().hex[:8]}")
    title: ShortText
    kind: ScheduleKind = "inspect"
    interval_days: int = Field(ge=1)
    last_done: Optional[date] = Field(default=None, description="Unknown = first task is due today")
    priority: Severity = "medium"
    notes: LongText = ""

    @computed_field
    @property
    def next_due(self) -> Optional[date]:
        return self.last_done + timedelta(days=self.interval_days) if self.last_done else None


class MaintenanceTask(BaseModel):
    id: str
    title: str
    description: str = ""
    due_date: date
    priority: Severity = "medium"
    status: TaskStatus = "open"
    source: Literal["manual", "diagnosis", "schedule"] = "manual"
    created_at: datetime
    schedule_id: Optional[str] = Field(
        default=None,
        description="Set on auto-generated tasks: service, calibration, stock, part:<name> or schedule:<id>",
    )
    completed_on: Optional[date] = None
    snoozed_until: Optional[date] = None
    notes: str = ""


class AssetBase(BaseModel):
    name: ShortText
    code: Optional[ShortText] = Field(default=None, description="Inventory code / SKU / catalog number / asset tag")
    category: ShortText = Field(default="general", description="e.g. centrifuge, autoclave, hplc, kit")
    manufacturer: Optional[ShortText] = None
    model: Optional[ShortText] = None
    serial_number: Optional[ShortText] = None
    location: Optional[ShortText] = None
    status: AssetStatus = "operational"
    last_service_date: Optional[date] = None
    service_interval_days: Optional[int] = Field(default=None, ge=1)
    last_calibration_date: Optional[date] = None
    calibration_interval_days: Optional[int] = Field(default=None, ge=1)
    parts: list[Part] = []
    environment: Environment = "lab"
    schedules: list[MaintenanceSchedule] = []
    manual_url: Optional[str] = Field(default=None, description="Link to the equipment manual")
    manual_id: Optional[str] = Field(default=None, description="Loaded manual, usable with /api/manual-query")
    quantity_expected: Optional[int] = Field(default=None, ge=0, description="Units there should be")
    quantity_actual: Optional[int] = Field(default=None, ge=0, description="Units last counted")
    groups: list[ShortText] = Field(default=[], description="Kits, sets or groups this item belongs to")
    notes: LongText = ""
    photo: Optional[str] = Field(default=None, description="Stored photo file name; fetch via photo_url")


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""

    name: Optional[ShortText] = None
    category: Optional[ShortText] = None
    manufacturer: Optional[ShortText] = None
    model: Optional[ShortText] = None
    serial_number: Optional[ShortText] = None
    location: Optional[ShortText] = None
    status: Optional[AssetStatus] = None
    last_service_date: Optional[date] = None
    service_interval_days: Optional[int] = Field(default=None, ge=1)
    last_calibration_date: Optional[date] = None
    calibration_interval_days: Optional[int] = Field(default=None, ge=1)
    parts: Optional[list[Part]] = None
    environment: Optional[Environment] = None
    schedules: Optional[list[MaintenanceSchedule]] = None
    manual_url: Optional[str] = None
    manual_id: Optional[str] = None
    code: Optional[ShortText] = None
    quantity_expected: Optional[int] = Field(default=None, ge=0)
    quantity_actual: Optional[int] = Field(default=None, ge=0)
    groups: Optional[list[ShortText]] = None
    notes: Optional[LongText] = None


class Asset(AssetBase):
    id: str
    tasks: list[MaintenanceTask] = []

    @computed_field
    @property
    def next_service_due(self) -> Optional[date]:
        if self.last_service_date and self.service_interval_days:
            return self.last_service_date + timedelta(days=self.service_interval_days)
        return None

    @computed_field
    @property
    def next_calibration_due(self) -> Optional[date]:
        if self.last_calibration_date and self.calibration_interval_days:
            return self.last_calibration_date + timedelta(days=self.calibration_interval_days)
        return None

    @computed_field
    @property
    def quantity_missing(self) -> Optional[int]:
        """Units short of expected (0 if complete or over); null if counts aren't tracked."""
        if self.quantity_expected is None or self.quantity_actual is None:
            return None
        return max(self.quantity_expected - self.quantity_actual, 0)

    @computed_field
    @property
    def photo_url(self) -> Optional[str]:
        return f"/api/assets/{self.id}/photo" if self.photo else None

    @computed_field
    @property
    def manual_search_url(self) -> Optional[str]:
        """Web search link for the manual; always available as a fallback."""
        terms = " ".join(filter(None, [self.manufacturer, self.model]))
        if not terms:
            return None
        return "https://www.google.com/search?q=" + quote_plus(f"{terms} user manual pdf")


class TaskCreate(BaseModel):
    title: ShortText
    description: LongText = ""
    due_date: date
    priority: Severity = "medium"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[Severity] = None
    status: Optional[TaskStatus] = None


class Alert(BaseModel):
    asset_id: str
    asset_name: str
    kind: TaskKind
    title: str
    due_date: date
    days_until_due: int = Field(description="Negative means overdue")
    priority: Severity


# --- Diagnose endpoint -------------------------------------------------------


class DiagnoseResponse(BaseModel):
    diagnosis: DiagnosisResult
    source: ResultSource = Field(description="model = real Gemma answer, mock = canned, fallback = model failed")
    task: Optional[MaintenanceTask] = Field(
        default=None, description="Task added to the asset's schedule when asset_id was given"
    )


# --- Manual assistant --------------------------------------------------------


class ManualInfo(BaseModel):
    id: str
    filename: str
    pages: int
    chars: int
    truncated: bool = Field(description="True if the manual was longer than the context budget")


class ManualQuery(BaseModel):
    manual_id: str
    question: str = Field(min_length=1)


class ManualAnswer(BaseModel):
    manual_id: str
    question: str
    answer: str
    pages_cited: list[int] = []
    source: ResultSource


# --- Inventory import (CSV / Excel) ------------------------------------------

ImportMode = Literal["append", "replace"]
MappingMethod = Literal["alias", "ai", "unmapped"]


class ColumnMapping(BaseModel):
    header: str
    field: Optional[str] = Field(description="Asset field this column fills, or null if ignored")
    method: MappingMethod


class ImportIssue(BaseModel):
    row: int = Field(description="Spreadsheet row number, as shown in Excel")
    message: str


class ImportResult(BaseModel):
    dry_run: bool
    mode: ImportMode
    file_type: Literal["csv", "xlsx"]
    sheet: Optional[str] = None
    header_row: int
    columns: list[ColumnMapping]
    ai_mapping: ResultSource | Literal["not_needed", "disabled"] = Field(
        description="How unmatched headers were handled: model/mock/fallback, not_needed, or disabled"
    )
    total_rows: int
    created: int = Field(description="New assets (would be created, on a dry run)")
    updated: int = Field(description="Existing assets matched by serial number")
    skipped: list[ImportIssue] = []
    warnings: list[ImportIssue] = []
    preview: list[AssetCreate] = Field(default=[], description="First parsed rows, to show before confirming")
    stock_mismatches: int = Field(default=0, description="Rows with fewer units counted than expected")
    kits_created: int = Field(default=0, description="Kit/group assets with a recurring stock count")


# --- Task manager -------------------------------------------------------------


class TaskView(MaintenanceTask):
    """A task plus the asset it belongs to, for the cross-asset task list."""

    asset_id: str
    asset_name: str
    kind: TaskKind
    days_until_due: int = Field(description="Negative means overdue")


class TaskComplete(BaseModel):
    completed_on: Optional[date] = Field(default=None, description="Defaults to today")
    notes: LongText = ""


class TaskSnooze(BaseModel):
    days: int = Field(ge=1, le=365)


class TaskCompleteResult(BaseModel):
    completed: MaintenanceTask
    next_task: Optional[MaintenanceTask] = Field(
        default=None, description="Next occurrence, for recurring tasks"
    )


# --- Identify (photo -> new asset) -------------------------------------------


class ScheduleSuggestion(BaseModel):
    """What Gemma returns per maintenance item; becomes a MaintenanceSchedule."""

    title: str
    kind: ScheduleKind = "inspect"
    frequency: Optional[str] = Field(default=None, description="In words, e.g. 'every 6 months'")
    interval_days: int = Field(ge=1, le=3650)
    priority: Severity = "medium"
    notes: str = ""


class IdentifiedItem(BaseModel):
    """What Gemma must return when identifying equipment from a photo."""

    name: str
    category: str
    environment: Environment = "household"
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    maintenance_plan: list[ScheduleSuggestion] = []


class Question(BaseModel):
    target: str = Field(description="Where the answer goes in the draft, e.g. 'manufacturer' or 'schedules.0.last_done'")
    prompt: str
    type: Literal["text", "date"]
    hint: Optional[str] = None
    required: bool = False


class IdentifyResult(BaseModel):
    draft: AssetCreate = Field(description="Fill in the answers, then POST it to /api/assets")
    questions: list[Question]
    confidence: float
    source: ResultSource


# --- Manual finder -----------------------------------------------------------


class ManualCandidate(BaseModel):
    title: str
    url: str
    is_pdf: bool
    score: int


class ManualLinkRequest(BaseModel):
    url: str = Field(pattern=r"^https?://")
    download: bool = Field(default=True, description="Try to download the PDF and load it for Q&A")


class FindManualResult(BaseModel):
    asset_id: str
    query: str
    search_url: str = Field(description="Open in a browser if nothing was found automatically")
    searched: bool = Field(description="False when no search provider is configured")
    candidates: list[ManualCandidate] = []
    manual_url: Optional[str] = Field(default=None, description="Link saved on the asset")
    manual: Optional[ManualInfo] = Field(default=None, description="Downloaded and loaded for Q&A")
    verified: bool = Field(default=False, description="Model number found inside the downloaded PDF")
    message: str


class PhotoImportResult(BaseModel):
    matched: int
    unmatched_files: list[str] = Field(default=[], description="Files whose name matched no asset code")
    assets_without_photo: int


# --- Assistant panel (frontend) ----------------------------------------------


class AssistantQuery(BaseModel):
    equipment_id: str
    message: str = Field(min_length=1, max_length=2000)


class AssistantAnswer(BaseModel):
    answer: str
    source: ResultSource
    pages_cited: list[int] = []
    used_manual: Optional[str] = Field(default=None, description="Manual file the answer came from, if any")
