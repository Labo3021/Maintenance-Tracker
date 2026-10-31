"""Proactive maintenance & reorder agent: runs in the background without a user prompt.

Each run: finds service/calibration/part work due within AGENT_DUE_DAYS (or overdue), finds stock
shortages, drafts purchase requisitions for shortages not already on an open requisition, and asks
Gemma for a short briefing. Detection is plain rules, so nothing is missed if the model is down;
the model only prioritizes and words the briefing.
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

from api.schemas import ProactiveReport, Requisition, RequisitionLine
from api.store import store
from config import settings

from . import gemma_client
from .prompts import PROACTIVE_PROMPT

log = logging.getLogger(__name__)

SCHEDULED_KINDS = {"service", "calibration", "part", "schedule"}


class ProactiveAgent:
    def __init__(self) -> None:
        self._lock = threading.Lock()  # one run at a time
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.next_run: Optional[datetime] = None
        self._state = self._load()

    @property
    def path(self):
        return settings.storage_dir / "agent_state.json"

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"last_run": None, "summary": "", "summary_source": "none", "requisitions": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)

    # --- findings ---

    def _findings(self):
        due = [a for a in store.alerts(within_days=settings.agent_due_days) if a.kind in SCHEDULED_KINDS]
        short = [a for a in store.list_assets() if a.quantity_missing]
        return due, short

    def _draft_requisitions(self, short) -> list[Requisition]:
        open_ids = {line["asset_id"] for r in self._state["requisitions"] if r["status"] != "dismissed"
                    for line in r["lines"]}
        by_source: dict[str, list[RequisitionLine]] = {}
        for a in short:
            if a.id in open_ids:
                continue
            reason = (f"None left (expected {a.quantity_expected})" if a.quantity_actual == 0
                      else f"Counted {a.quantity_actual} of {a.quantity_expected}")
            by_source.setdefault(a.source or "other", []).append(RequisitionLine(
                asset_id=a.id, name=a.name, code=a.code, quantity=a.quantity_missing, location=a.location,
                purchase_url=a.purchase_url, reason=reason))
        return [Requisition(id=f"req-{uuid.uuid4().hex[:8]}", created_at=datetime.now(), source=source, lines=lines)
                for source, lines in by_source.items()]

    def _briefing(self, due, short, new_reqs) -> tuple[str, str]:
        overdue = [a for a in due if a.days_until_due < 0]
        empty = [a for a in short if a.quantity_actual == 0]
        fallback = (f"{len(overdue)} maintenance item(s) are overdue and {len(due) - len(overdue)} are due within "
                    f"{settings.agent_due_days} days. {len(short)} stock item(s) are short, {len(empty)} with none left."
                    + (f" Drafted {sum(len(r.lines) for r in new_reqs)} purchase requisition line(s)." if new_reqs else ""))
        if gemma_client.is_mock():
            return fallback, "mock"
        lines = [f"- {a.asset_name}: {a.title} ({'overdue by ' + str(-a.days_until_due) + ' days' if a.days_until_due < 0 else 'due in ' + str(a.days_until_due) + ' days'}, {a.priority})"
                 for a in due[:12]]
        lines += [f"- Stock: {a.name} has {a.quantity_actual} of {a.quantity_expected}" for a in
                  sorted(short, key=lambda a: (a.quantity_actual or 0, -(a.quantity_missing or 0)))[:12]]
        if new_reqs:
            lines.append(f"- New purchase requisition drafted with {sum(len(r.lines) for r in new_reqs)} line(s)")
        try:
            text = gemma_client.generate(PROACTIVE_PROMPT.format(findings="\n".join(lines) or "- Nothing due."))
            return (text.strip() or fallback), "model"
        except gemma_client.GemmaError as e:
            log.warning("Proactive briefing failed: %s", e)
            return fallback, "fallback"

    # --- running ---

    def run(self) -> ProactiveReport:
        if not self._lock.acquire(blocking=False):
            return self.report()  # a run is already in progress
        try:
            due, short = self._findings()
            with self._state_lock:
                new_reqs = self._draft_requisitions(short)
                self._state["requisitions"] = [r.model_dump(mode="json") for r in new_reqs] + self._state["requisitions"]
            summary, source = self._briefing(due, short, new_reqs)
            with self._state_lock:
                self._state.update(last_run=datetime.now().isoformat(), summary=summary, summary_source=source)
                self._save()
            log.info("Proactive agent: %d due, %d short, %d new requisition(s)", len(due), len(short), len(new_reqs))
            return self.report()
        finally:
            self._lock.release()

    def report(self) -> ProactiveReport:
        due, short = self._findings()
        with self._state_lock:
            state = dict(self._state)
            reqs = [Requisition.model_validate(r) for r in state["requisitions"]]
        return ProactiveReport(
            last_run=state["last_run"], next_run=self.next_run, running=self._lock.locked(),
            summary=state["summary"], summary_source=state["summary_source"], due_soon=due,
            shortages=len(short), out_of_stock=sum(1 for a in short if a.quantity_actual == 0),
            requisitions=reqs,
        )

    def set_status(self, req_id: str, status: str) -> Optional[Requisition]:
        with self._state_lock:
            for r in self._state["requisitions"]:
                if r["id"] == req_id:
                    r["status"] = status
                    self._save()
                    return Requisition.model_validate(r)
        return None

    def start(self, first_delay_seconds: float = 20) -> None:
        """Background loop: first run shortly after startup, then every AGENT_INTERVAL_MINUTES."""
        if settings.agent_interval_minutes <= 0 or self._thread is not None:
            return

        def loop():
            delay = first_delay_seconds
            while True:
                self.next_run = datetime.now() + timedelta(seconds=delay)
                if self._stop.wait(delay):
                    return
                try:
                    self.run()
                except Exception:  # keep the loop alive whatever happens in one run
                    log.exception("Proactive agent run failed")
                delay = settings.agent_interval_minutes * 60

        self._thread = threading.Thread(target=loop, name="proactive-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


agent = ProactiveAgent()
