"""Data contracts shared by the API routes, the AI layer, and the frontend.

Change these only with the whole team: the frontend builds against the shapes
shown at http://localhost:8000/docs.
"""

from datetime import date, datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field

Severity = Literal["low", "medium", "high", "critical"]
AssetStatus = Literal["operational", "needs_attention", "out_of_service"]
TaskStatus = Literal["open", "done"]
ResultSource = Literal["model", "mock", "fallback"]


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


class MaintenanceTask(BaseModel):
    id: str
    title: str
    description: str = ""
    due_date: date
    priority: Severity = "medium"
    status: TaskStatus = "open"
    source: Literal["manual", "diagnosis"] = "manual"
    created_at: datetime


class AssetBase(BaseModel):
    name: str
    category: str = Field(default="general", description="e.g. centrifuge, autoclave, hplc")
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    status: AssetStatus = "operational"
    last_service_date: Optional[date] = None
    service_interval_days: Optional[int] = Field(default=None, ge=1)
    last_calibration_date: Optional[date] = None
    calibration_interval_days: Optional[int] = Field(default=None, ge=1)
    parts: list[Part] = []


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""

    name: Optional[str] = None
    category: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    status: Optional[AssetStatus] = None
    last_service_date: Optional[date] = None
    service_interval_days: Optional[int] = Field(default=None, ge=1)
    last_calibration_date: Optional[date] = None
    calibration_interval_days: Optional[int] = Field(default=None, ge=1)
    parts: Optional[list[Part]] = None


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


class TaskCreate(BaseModel):
    title: str
    description: str = ""
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
    kind: Literal["service", "calibration", "part", "task"]
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
