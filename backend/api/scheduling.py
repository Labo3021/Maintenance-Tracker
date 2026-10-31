"""Turns an asset's recurring maintenance into concrete tasks.

Every recurring source (service interval, calibration interval, part lifespan,
custom schedule) keeps exactly one open task, keyed by `schedule_id`. Completing
that task records the date on the source, and the next sync creates the next one.
Manual and diagnosis tasks (schedule_id = None) are never touched here.
"""

import uuid
from datetime import date, datetime
from typing import Optional

from .schemas import Asset, MaintenanceTask, Severity, TaskKind


def _desired(asset: Asset) -> dict[str, tuple[str, str, Optional[date], Severity]]:
    """schedule_id -> (title, description, due date, priority) for everything recurring.
    A None due date means "due now": today when first created, then it stays put (and goes overdue)."""
    out: dict[str, tuple[str, str, Optional[date], Severity]] = {}
    missing = asset.quantity_missing
    if missing:
        out["stock"] = (
            f"Missing {missing} unit{'s' if missing > 1 else ''}: {asset.name}",
            f"Counted {asset.quantity_actual} of {asset.quantity_expected}. Locate or reorder; "
            "completing this task sets the count back to the expected amount.",
            None,
            "high" if asset.quantity_actual == 0 else "medium",
        )
    if asset.next_service_due:
        out["service"] = ("Scheduled service", "", asset.next_service_due, "medium")
    if asset.next_calibration_due:
        out["calibration"] = ("Calibration", "", asset.next_calibration_due, "high")
    for part in asset.parts:
        if part.replace_by:
            out[f"part:{part.name}"] = (f"Replace {part.name}", part.part_number or "", part.replace_by, "medium")
    for s in asset.schedules:
        if s.next_due:
            out[f"schedule:{s.id}"] = (s.title, s.notes, s.next_due, s.priority)
        else:
            note = "No record of when this was last done, so it's due now. " + s.notes
            out[f"schedule:{s.id}"] = (s.title, note.strip(), None, s.priority)
    return out


def sync_tasks(asset: Asset) -> None:
    """Create, re-date, or drop auto-generated open tasks so they match the asset's schedules."""
    desired = _desired(asset)
    open_by_key = {t.schedule_id: t for t in asset.tasks if t.schedule_id and t.status == "open"}

    # Drop open tasks whose source was removed (e.g. schedule deleted, interval cleared).
    asset.tasks = [t for t in asset.tasks if not (t.schedule_id and t.status == "open" and t.schedule_id not in desired)]

    for key, (title, description, due, priority) in desired.items():
        task = open_by_key.get(key)
        if due is None:
            due = task.due_date if task else date.today()
        if task and task.snoozed_until:
            due = max(due, task.snoozed_until)
        if task is None:
            asset.tasks.append(
                MaintenanceTask(
                    id=f"task-{uuid.uuid4().hex[:8]}",
                    title=title,
                    description=description,
                    due_date=due,
                    priority=priority,
                    source="schedule",
                    schedule_id=key,
                    created_at=datetime.now(),
                )
            )
        else:
            task.title, task.description, task.due_date, task.priority = title, description, due, priority


def record_completion(asset: Asset, schedule_id: Optional[str], done_on: date) -> Asset:
    """Write the completion date back to whatever produced the task. Returns an updated copy."""
    if not schedule_id:
        return asset
    data = asset.model_dump()
    if schedule_id == "service":
        data["last_service_date"] = done_on
    elif schedule_id == "calibration":
        data["last_calibration_date"] = done_on
    elif schedule_id == "stock":
        data["quantity_actual"] = data["quantity_expected"]  # found or reordered
    elif schedule_id.startswith("part:"):
        name = schedule_id.removeprefix("part:")
        for part in data["parts"]:
            if part["name"] == name:
                part["installed_date"] = done_on
    elif schedule_id.startswith("schedule:"):
        sid = schedule_id.removeprefix("schedule:")
        for s in data["schedules"]:
            if s["id"] == sid:
                s["last_done"] = done_on
    return Asset.model_validate(data)


def task_kind(task: MaintenanceTask) -> TaskKind:
    if not task.schedule_id:
        return "task"
    prefix = task.schedule_id.split(":", 1)[0]
    return prefix if prefix in ("service", "calibration", "part", "schedule", "stock") else "task"
