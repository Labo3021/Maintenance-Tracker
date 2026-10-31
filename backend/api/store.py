"""JSON-file persistence for the inventory and its tasks.

On first run the store is seeded from data/mock_inventory.json (owned by the data
lead) or, if that file doesn't exist yet, from backend/seed/mock_inventory.json.
All writes go to storage/inventory.json so data/ is never modified.
"""

import json
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from config import BACKEND_DIR, settings

from .schemas import (
    Alert,
    Asset,
    AssetCreate,
    AssetUpdate,
    DiagnosisResult,
    MaintenanceTask,
    TaskCreate,
    TaskUpdate,
    TaskView,
)
from .scheduling import record_completion, sync_tasks, task_kind

# How soon a diagnosis-generated task is due, by severity.
DUE_IN_DAYS = {"critical": 0, "high": 2, "medium": 7, "low": 30}
PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class InventoryStore:
    def __init__(self, path: Path, seed_paths: list[Path]) -> None:
        self.path = path
        self.seed_paths = seed_paths
        self._lock = threading.Lock()
        self._assets: dict[str, Asset] = {}
        self._load()

    # --- persistence ---

    def _load(self) -> None:
        source = self.path if self.path.exists() else next((p for p in self.seed_paths if p.exists()), None)
        if source is None:
            return
        raw = json.loads(source.read_text(encoding="utf-8"))
        items = raw.get("assets", raw) if isinstance(raw, dict) else raw
        for item in items:
            item.setdefault("id", _new_id("asset"))
            asset = Asset.model_validate(item)
            sync_tasks(asset)
            self._assets[asset.id] = asset
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Computed fields (next_*_due, replace_by...) are saved too but ignored on load.
        data = {"assets": [a.model_dump(mode="json") for a in self._assets.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # --- assets ---

    def list_assets(self, category: Optional[str] = None, status: Optional[str] = None) -> list[Asset]:
        assets = list(self._assets.values())
        if category:
            assets = [a for a in assets if a.category.lower() == category.lower()]
        if status:
            assets = [a for a in assets if a.status == status]
        return assets

    def get(self, asset_id: str) -> Optional[Asset]:
        return self._assets.get(asset_id)

    def _put(self, asset: Asset) -> Asset:
        """Store an asset after regenerating its recurring tasks. Caller holds the lock and saves."""
        sync_tasks(asset)
        self._assets[asset.id] = asset
        return asset

    def create(self, data: AssetCreate) -> Asset:
        with self._lock:
            asset = self._put(Asset(id=_new_id("asset"), **data.model_dump()))
            self._save()
            return asset

    def update(self, asset_id: str, data: AssetUpdate) -> Optional[Asset]:
        with self._lock:
            asset = self._assets.get(asset_id)
            if asset is None:
                return None
            merged = asset.model_dump() | data.model_dump(exclude_unset=True)
            asset = self._put(Asset.model_validate(merged))
            self._save()
            return asset

    def import_assets(
        self, rows: list[tuple[AssetCreate, list[TaskCreate]]], mode: str = "append"
    ) -> tuple[int, int]:
        """Bulk import. Rows whose serial number already exists update that asset
        (only the columns present in the file); the rest are created. Returns (created, updated)."""
        with self._lock:
            if mode == "replace":
                self._assets.clear()
            by_serial = {a.serial_number.strip().lower(): a.id for a in self._assets.values() if a.serial_number}
            created = updated = 0
            for data, tasks in rows:
                serial = (data.serial_number or "").strip().lower()
                asset_id = by_serial.get(serial) if serial else None
                if asset_id:
                    existing = self._assets[asset_id]
                    # Serials match case-insensitively; keep the stored spelling.
                    merged = existing.model_dump() | data.model_dump(exclude_unset=True, exclude={"serial_number"})
                    asset = Asset.model_validate(merged)
                    updated += 1
                else:
                    asset = Asset(id=_new_id("asset"), **data.model_dump())
                    if serial:
                        by_serial[serial] = asset.id
                    created += 1
                for t in tasks:
                    asset.tasks.append(MaintenanceTask(id=_new_id("task"), created_at=datetime.now(), **t.model_dump()))
                self._put(asset)
            self._save()
            return created, updated

    def delete(self, asset_id: str) -> bool:
        with self._lock:
            if self._assets.pop(asset_id, None) is None:
                return False
            self._save()
            return True

    # --- tasks ---

    def add_task(self, asset_id: str, data: TaskCreate, source: str = "manual") -> Optional[MaintenanceTask]:
        with self._lock:
            asset = self._assets.get(asset_id)
            if asset is None:
                return None
            task = MaintenanceTask(id=_new_id("task"), created_at=datetime.now(), source=source, **data.model_dump())
            asset.tasks.append(task)
            self._save()
            return task

    def update_task(self, asset_id: str, task_id: str, data: TaskUpdate) -> Optional[MaintenanceTask]:
        changes = data.model_dump(exclude_unset=True)
        if changes.get("status") == "done":
            # Marking done must also roll recurring tasks forward.
            found = self.find_task(task_id)
            if found is None or found[0].id != asset_id:
                return None
            if found[1].status == "open":
                done, _ = self.complete_task(task_id)
                changes.pop("status")
                if not changes:
                    return done
        with self._lock:
            asset = self._assets.get(asset_id)
            if asset is None:
                return None
            for i, task in enumerate(asset.tasks):
                if task.id == task_id:
                    updated = task.model_copy(update=changes)
                    asset.tasks[i] = updated
                    self._save()
                    return updated
            return None

    def find_task(self, task_id: str) -> Optional[tuple[Asset, MaintenanceTask]]:
        for asset in self._assets.values():
            for task in asset.tasks:
                if task.id == task_id:
                    return asset, task
        return None

    def list_tasks(
        self,
        status: Optional[str] = "open",
        within_days: Optional[int] = None,
        asset_id: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> list[TaskView]:
        """All tasks across assets, soonest first. within_days always includes overdue tasks."""
        today = date.today()
        out = []
        for asset in self._assets.values():
            if asset_id and asset.id != asset_id:
                continue
            if environment and asset.environment != environment:
                continue
            for task in asset.tasks:
                days = (task.due_date - today).days
                if status and task.status != status:
                    continue
                if within_days is not None and days > within_days:
                    continue
                out.append(
                    TaskView(
                        **task.model_dump(),
                        asset_id=asset.id,
                        asset_name=asset.name,
                        kind=task_kind(task),
                        days_until_due=days,
                    )
                )
        return sorted(out, key=lambda t: (t.status == "done", t.due_date, -PRIORITY_RANK[t.priority]))

    def complete_task(
        self, task_id: str, completed_on: Optional[date] = None, notes: str = ""
    ) -> Optional[tuple[MaintenanceTask, Optional[MaintenanceTask]]]:
        """Mark done; for recurring tasks record the date on the source and return the next task."""
        with self._lock:
            found = self.find_task(task_id)
            if found is None:
                return None
            asset, task = found
            done_on = completed_on or date.today()
            done = task.model_copy(update={"status": "done", "completed_on": done_on, "notes": notes or task.notes})
            asset.tasks = [done if t.id == task_id else t for t in asset.tasks]
            if task.status == "open" and task.schedule_id:
                asset = self._put(record_completion(asset, task.schedule_id, done_on))
            self._save()
            nxt = None
            if task.schedule_id:
                nxt = next((t for t in asset.tasks if t.schedule_id == task.schedule_id and t.status == "open"), None)
            return done, nxt

    def snooze_task(self, task_id: str, days: int) -> Optional[MaintenanceTask]:
        with self._lock:
            found = self.find_task(task_id)
            if found is None:
                return None
            asset, task = found
            new_due = max(task.due_date, date.today()) + timedelta(days=days)
            snoozed = task.model_copy(update={"due_date": new_due, "snoozed_until": new_due})
            asset.tasks = [snoozed if t.id == task_id else t for t in asset.tasks]
            self._save()
            return snoozed

    def add_task_from_diagnosis(self, asset_id: str, diagnosis: DiagnosisResult) -> Optional[MaintenanceTask]:
        """Turn an AI diagnosis into a scheduled task and flag the asset."""
        task = self.add_task(
            asset_id,
            TaskCreate(
                title=f"{diagnosis.component}: {diagnosis.issue}"[:120],
                description="\n".join(f"{s.step}. {s.instruction}" for s in diagnosis.steps),
                due_date=date.today() + timedelta(days=DUE_IN_DAYS[diagnosis.severity]),
                priority=diagnosis.severity,
            ),
            source="diagnosis",
        )
        if task and diagnosis.severity in ("high", "critical"):
            status = "out_of_service" if diagnosis.severity == "critical" else "needs_attention"
            self.update(asset_id, AssetUpdate(status=status))
        return task

    # --- alerts & reminders ---

    def alerts(self, within_days: int = 30) -> list[Alert]:
        """Open tasks due within the window (overdue included); overdue ones are at least high priority."""
        out = []
        for t in self.list_tasks(status="open", within_days=within_days):
            priority = t.priority
            if t.days_until_due < 0 and PRIORITY_RANK[priority] < PRIORITY_RANK["high"]:
                priority = "high"
            out.append(
                Alert(
                    asset_id=t.asset_id,
                    asset_name=t.asset_name,
                    kind=t.kind,
                    title=t.title,
                    due_date=t.due_date,
                    days_until_due=t.days_until_due,
                    priority=priority,
                )
            )
        return out

    def reminders(self, days_before: int) -> list[TaskView]:
        """What to notify about right now: overdue or due within `days_before` days."""
        return self.list_tasks(status="open", within_days=days_before)


store = InventoryStore(
    path=settings.storage_dir / "inventory.json",
    seed_paths=[settings.data_dir / "mock_inventory.json", BACKEND_DIR / "seed" / "mock_inventory.json"],
)
