"""JSON-file persistence for the inventory and its tasks.

On first run the store is seeded from data/mock_inventory.json (owned by the data
lead) or, if that file doesn't exist yet, from backend/seed/mock_inventory.json.
All writes go to storage/inventory.json so data/ is never modified.
"""

import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from config import BACKEND_DIR, settings

from .schemas import (
    Alert,
    Asset,
    AssetCreate,
    AssetUpdate,
    DiagnosisResult,
    MaintenanceSchedule,
    MaintenanceTask,
    TaskCreate,
    TaskUpdate,
    TaskView,
)
from .scheduling import interval_for, record_completion, sync_tasks, task_kind

# How soon a diagnosis-generated task is due, by severity.
DUE_IN_DAYS = {"critical": 0, "high": 2, "medium": 7, "low": 30}
PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class TaskConflict(ValueError):
    """The requested task change isn't allowed (e.g. reopening a recurring task)."""


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class MatchIndex:
    """Finds the existing asset an imported row refers to: by serial number, else by code."""

    def __init__(self, assets) -> None:
        self.by_serial: dict[str, str] = {}
        self.by_code: dict[str, str] = {}
        for a in assets:
            self.add(a, a.id)

    @staticmethod
    def _key(value: Optional[str]) -> str:
        return (value or "").strip().lower()

    def find(self, data) -> Optional[str]:
        serial, code = self._key(data.serial_number), self._key(data.code)
        return (self.by_serial.get(serial) if serial else None) or (self.by_code.get(code) if code else None)

    def add(self, data, asset_id: str) -> None:
        if serial := self._key(data.serial_number):
            self.by_serial.setdefault(serial, asset_id)
        if code := self._key(data.code):
            self.by_code.setdefault(code, asset_id)


class InventoryStore:
    def __init__(self, path: Path, seeds: list[tuple[Path, dict]]) -> None:
        """seeds: (json file, defaults for fields the file leaves out). All existing files are
        loaded on first run; after that the saved inventory is the only source."""
        self.path = path
        self.seeds = seeds
        self.fresh = False  # True when this run started from the seeds (no saved inventory)
        # Writers never mutate a stored Asset in place: they build a new one and swap it in,
        # so a reader holding a snapshot (or a response being serialized) never sees a half-done change.
        self._lock = threading.RLock()
        self._assets: dict[str, Asset] = {}
        self._load()

    # --- persistence ---

    def _load(self) -> None:
        if self.path.exists():
            sources = [(self.path, {})]
        else:
            sources = [(p, d) for p, d in self.seeds if p.exists()]
            self.fresh = True
        for source, defaults in sources:
            raw = json.loads(source.read_text(encoding="utf-8"))
            items = raw.get("assets", raw) if isinstance(raw, dict) else raw
            for item in items:
                item = defaults | item
                item.setdefault("id", _new_id("asset"))
                if item["id"] in self._assets:
                    continue  # first source wins on an ID clash
                asset = Asset.model_validate(item)
                sync_tasks(asset)
                self._assets[asset.id] = asset
        if sources:
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Computed fields (next_*_due, replace_by...) are saved too but ignored on load.
        data = {"assets": [a.model_dump(mode="json") for a in self._assets.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # --- assets ---

    def _snapshot(self) -> list[Asset]:
        with self._lock:
            return list(self._assets.values())

    def list_assets(self, category: Optional[str] = None, status: Optional[str] = None) -> list[Asset]:
        assets = self._snapshot()
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
        """Bulk import. Rows whose serial number (or, failing that, code) already exists update
        that asset (only the columns present in the file); the rest are created. Returns (created, updated)."""
        with self._lock:
            if mode == "replace":
                self._assets.clear()
            index = MatchIndex(self._assets.values())
            created = updated = 0
            for data, tasks in rows:
                asset_id = index.find(data)
                if asset_id:
                    existing = self._assets[asset_id]
                    # Keys match case-insensitively; keep the stored spelling.
                    merged = existing.model_dump() | data.model_dump(
                        exclude_unset=True, exclude={"serial_number", "code"}
                    )
                    asset = Asset.model_validate(merged)
                    updated += 1
                else:
                    asset = Asset(id=_new_id("asset"), **data.model_dump())
                    created += 1
                index.add(asset, asset.id)
                for t in tasks:
                    asset.tasks.append(MaintenanceTask(id=_new_id("task"), created_at=datetime.now(), **t.model_dump()))
                self._put(asset)
            self._save()
            return created, updated

    # --- photos ---

    @property
    def photo_dir(self) -> Path:
        return self.path.parent / "photos"

    def set_photo(self, asset_id: str, data: bytes, ext: str) -> Optional[Asset]:
        with self._lock:
            asset = self._assets.get(asset_id)
            if asset is None:
                return None
            self.photo_dir.mkdir(parents=True, exist_ok=True)
            if asset.photo:
                (self.photo_dir / asset.photo).unlink(missing_ok=True)
            name = f"{asset_id}{ext}"
            (self.photo_dir / name).write_bytes(data)
            asset = asset.model_copy(update={"photo": name})
            self._assets[asset_id] = asset
            self._save()
            return asset

    def attach_photos_by_code(
        self, files: Iterable[tuple[str, int, Callable[[], bytes]]], max_bytes: int
    ) -> tuple[int, list[str]]:
        """files: (file name, size, read function). Each image whose name (without extension) matches an
        asset code is attached; '03065-20.jpg' matches code '03065.20'. A .jpg beats other formats for the
        same code. Returns (matched assets, unmatched file names)."""
        key = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
        by_code = {key(a.code): a.id for a in self._snapshot() if a.code}
        done: set[str] = set()
        unmatched: list[str] = []
        for name, size, read in sorted(files, key=lambda f: (Path(f[0]).suffix.lower() != ".jpg", f[0])):
            asset_id = by_code.get(key(Path(name).stem))
            if asset_id is None:
                unmatched.append(name)
            elif asset_id not in done and size <= max_bytes:
                self.set_photo(asset_id, read(), Path(name).suffix.lower())
                done.add(asset_id)
        return len(done), unmatched

    def photo_path(self, asset_id: str) -> Optional[Path]:
        asset = self._assets.get(asset_id)
        if asset is None or not asset.photo:
            return None
        path = self.photo_dir / asset.photo
        return path if path.exists() else None

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
            if data.repeat_every_days:
                # A recurring task is a schedule whose first occurrence falls on due_date.
                n = data.repeat_every_days
                schedule = MaintenanceSchedule(title=data.title, interval_days=n, priority=data.priority,
                                               last_done=data.due_date - timedelta(days=n), notes=data.description)
                asset = self._put(asset.model_copy(update={"schedules": [*asset.schedules, schedule]}))
                self._save()
                return next(t for t in asset.tasks if t.schedule_id == f"schedule:{schedule.id}")
            task = MaintenanceTask(id=_new_id("task"), created_at=datetime.now(), source=source,
                                   **data.model_dump(exclude={"repeat_every_days"}))
            self._assets[asset_id] = asset.model_copy(update={"tasks": [*asset.tasks, task]})
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
            for task in asset.tasks:
                if task.id == task_id:
                    if changes.get("status") == "open" and task.status == "done" and task.schedule_id:
                        raise TaskConflict(
                            "Recurring tasks can't be reopened: the next occurrence is already scheduled."
                        )
                    updated = task.model_copy(update=changes)
                    tasks = [updated if t.id == task_id else t for t in asset.tasks]
                    self._assets[asset_id] = asset.model_copy(update={"tasks": tasks})
                    self._save()
                    return updated
            return None

    def find_task(self, task_id: str) -> Optional[tuple[Asset, MaintenanceTask]]:
        for asset in self._snapshot():
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
        for asset in self._snapshot():
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
                        interval_days=interval_for(asset, task.schedule_id),
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
            asset = asset.model_copy(update={"tasks": [done if t.id == task_id else t for t in asset.tasks]})
            if task.status == "open" and task.schedule_id:
                asset = self._put(record_completion(asset, task.schedule_id, done_on))
            else:
                self._assets[asset.id] = asset
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
            self._assets[asset.id] = asset.model_copy(
                update={"tasks": [snoozed if t.id == task_id else t for t in asset.tasks]}
            )
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
    seeds=[
        (BACKEND_DIR / "seed" / "mock_inventory.json", {"environment": "lab"}),        # demo lab instruments
        (settings.data_dir / "mock_inventory.json", {"environment": "household"}),     # data/: household tasks
    ],
)
