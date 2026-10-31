"""JSON-file persistence for the lab inventory.

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
)

# How soon a diagnosis-generated task is due, by severity.
DUE_IN_DAYS = {"critical": 0, "high": 2, "medium": 7, "low": 30}


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
            self._assets[asset.id] = asset
        if source != self.path:
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Computed fields are derived on load, so don't persist them.
        data = {
            "assets": [
                a.model_dump(
                    mode="json",
                    exclude={
                        "next_service_due": True,
                        "next_calibration_due": True,
                        "parts": {"__all__": {"replace_by"}},
                    },
                )
                for a in self._assets.values()
            ]
        }
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

    def create(self, data: AssetCreate) -> Asset:
        with self._lock:
            asset = Asset(id=_new_id("asset"), **data.model_dump())
            self._assets[asset.id] = asset
            self._save()
            return asset

    def update(self, asset_id: str, data: AssetUpdate) -> Optional[Asset]:
        with self._lock:
            asset = self._assets.get(asset_id)
            if asset is None:
                return None
            merged = asset.model_dump() | data.model_dump(exclude_unset=True)
            asset = Asset.model_validate(merged)
            self._assets[asset_id] = asset
            self._save()
            return asset

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
        with self._lock:
            asset = self._assets.get(asset_id)
            if asset is None:
                return None
            for i, task in enumerate(asset.tasks):
                if task.id == task_id:
                    updated = task.model_copy(update=data.model_dump(exclude_unset=True))
                    asset.tasks[i] = updated
                    self._save()
                    return updated
            return None

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

    # --- alerts ---

    def alerts(self, within_days: int = 30) -> list[Alert]:
        today = date.today()
        out: list[Alert] = []

        def add(asset: Asset, kind: str, title: str, due: Optional[date], priority: Optional[str] = None) -> None:
            if due is None:
                return
            days = (due - today).days
            if days > within_days:
                return
            if priority is None:
                priority = "critical" if days < 0 else "high" if days <= 7 else "medium"
            out.append(
                Alert(
                    asset_id=asset.id,
                    asset_name=asset.name,
                    kind=kind,
                    title=title,
                    due_date=due,
                    days_until_due=days,
                    priority=priority,
                )
            )

        for asset in self._assets.values():
            add(asset, "service", "Scheduled service", asset.next_service_due)
            add(asset, "calibration", "Calibration due", asset.next_calibration_due)
            for part in asset.parts:
                add(asset, "part", f"Replace {part.name}", part.replace_by)
            for task in asset.tasks:
                if task.status == "open":
                    add(asset, "task", task.title, task.due_date, task.priority)

        return sorted(out, key=lambda a: a.days_until_due)


store = InventoryStore(
    path=settings.storage_dir / "inventory.json",
    seed_paths=[settings.data_dir / "mock_inventory.json", BACKEND_DIR / "seed" / "mock_inventory.json"],
)
