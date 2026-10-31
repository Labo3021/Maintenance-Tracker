"""Diagnostic agent: Gemma chooses backend tools in a loop, then writes one action report.

Tools: inspect_image, check_inventory, query_manual, schedule_task. Guardrails for a small model:
a step limit, no repeated calls, argument checks, and a fixed "guided" tool order if the model
goes off track. Stock and actions in the report come from what the tools returned, never from
what the model says.
"""

import json
import logging
import re
from datetime import date, timedelta
from typing import Optional

from api.schemas import (
    AgentDiagnoseResponse,
    AgentReport,
    AgentStep,
    Asset,
    DiagnosisResult,
    MaintenanceTask,
    StockCheck,
    TaskCreate,
)
from api.store import store
from config import settings

from . import gemma_client, manuals
from .assistant import setting_key
from .diagnose import diagnose_image
from .prompts import AGENT_PROMPT, setting_guidance

log = logging.getLogger(__name__)

PRIORITIES = ("low", "medium", "high", "critical")
STOPWORDS = {"the", "a", "an", "of", "for", "and", "or", "with", "this", "that", "replacement", "new", "part", "parts",
             "kit", "oem", "model", "compatible", "specific", "appropriate", "genuine", "spare", "de", "del", "la", "el",
             "para", "con", "y"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in STOPWORDS}


class Run:
    """State of one agent run: the photo, the chosen asset, and everything the tools found."""

    def __init__(self, image: bytes, mime: str, asset: Optional[Asset], notes: Optional[str]):
        self.image, self.mime, self.asset, self.notes = image, mime, asset, notes
        self.steps: list[AgentStep] = []
        self.diagnosis: Optional[DiagnosisResult] = None
        self.stock: dict[str, StockCheck] = {}
        self.manual_notes: list[str] = []
        self.task: Optional[MaintenanceTask] = None
        self.calls: set[str] = set()

    # --- tools ---

    def inspect_image(self) -> str:
        hint = " ".join(filter(None, [self.asset.manufacturer, self.asset.model, self.asset.name])) if self.asset else None
        env = setting_key(self.asset) if self.asset else None
        self.diagnosis, source = diagnose_image(self.image, self.mime, equipment_hint=hint, notes=self.notes,
                                                environment=env)
        d = self.diagnosis
        if source == "fallback":
            return "Image inspection failed (model unavailable). Give safe, generic advice."
        return json.dumps({"component": d.component, "issue": d.issue, "severity": d.severity,
                           "parts_needed": d.parts_needed, "hazards": [h.type for h in d.hazards],
                           "requires_technician": d.requires_technician}, ensure_ascii=False)

    def check_inventory(self, part_name: str) -> str:
        wanted = _words(part_name)
        best, best_score = None, 0.0
        for a in store.list_assets():
            if a.category == "kit":
                continue
            have = _words(" ".join(filter(None, [a.name, a.code, a.model, a.manufacturer])))
            if not have:
                continue
            # Models describe parts verbosely ("replacement lid gasket for this unit"), so compare against
            # the shorter of the two names and require 2 shared words when both names have 2+.
            overlap = len(wanted & have)
            if overlap < min(2, len(wanted), len(have)):
                continue
            score = overlap / min(len(wanted), len(have))
            tracked = a.quantity_actual is not None
            if score > best_score or (score == best_score and tracked):
                best, best_score = a, score
        if best is None or best_score < 0.5:
            self.stock[part_name] = StockCheck(part=part_name)
            return f"No inventory item matches '{part_name}'. It is not stocked here."
        check = StockCheck(part=part_name, match=best.name, asset_id=best.id, location=best.location,
                           quantity=best.quantity_actual,
                           in_stock=None if best.quantity_actual is None else best.quantity_actual > 0)
        self.stock[part_name] = check
        qty = "quantity not tracked" if check.quantity is None else f"{check.quantity} on hand"
        return f"Best match: '{best.name}' ({qty}, location: {best.location or 'unknown'})."

    def query_manual(self, question: str) -> str:
        manual = manuals.get_manual(self.asset.manual_id) if self.asset and self.asset.manual_id else None
        if manual is None:
            return "No manual is linked to this equipment."
        result = manuals.ask(manual, question)
        pages = f" (pages {', '.join(map(str, result.pages_cited))})" if result.pages_cited else ""
        self.manual_notes.append(result.answer + pages)
        return result.answer + pages

    def schedule_task(self, title: str, priority: str = "medium", due_in_days: int = 2) -> str:
        if self.asset is None:
            return "No equipment selected, so nothing can be scheduled."
        if self.task is not None:
            return f"Already scheduled: '{self.task.title}'."
        priority = priority if priority in PRIORITIES else "medium"
        due_in_days = max(0, min(int(due_in_days), 90))
        description = ""
        if self.diagnosis:
            description = "\n".join(f"{s.step}. {s.instruction}" for s in self.diagnosis.steps)
        self.task = store.add_task(self.asset.id, TaskCreate(
            title=title[:200], description=description[:5000], priority=priority,
            due_date=date.today() + timedelta(days=due_in_days)), source="diagnosis")
        return f"Scheduled '{self.task.title}' ({priority}) due {self.task.due_date}."

    def call(self, tool: str, args: dict, thought: str = "") -> str:
        key = f"{tool}:{json.dumps(args, sort_keys=True)}"
        if key in self.calls:
            result = "You already called this tool with these arguments. Use another tool or finish."
        else:
            self.calls.add(key)
            try:
                if tool == "inspect_image":
                    result = self.inspect_image()
                elif tool == "check_inventory" and str(args.get("part_name", "")).strip():
                    result = self.check_inventory(str(args["part_name"])[:120])
                elif tool == "query_manual" and str(args.get("question", "")).strip():
                    result = self.query_manual(str(args["question"])[:500])
                elif tool == "schedule_task" and str(args.get("title", "")).strip():
                    result = self.schedule_task(str(args["title"]), str(args.get("priority", "medium")),
                                                int(args.get("due_in_days", 2) or 2))
                else:
                    result = f"Unknown tool or missing arguments: {tool} {args}"
            except (ValueError, TypeError) as e:
                result = f"Tool error: {e}"
        self.steps.append(AgentStep(tool=tool, args=args, thought=thought[:300], result=result[:600]))
        return result

    # --- report ---

    def report(self, final: Optional[dict] = None) -> AgentReport:
        final = final or {}
        d = self.diagnosis
        safety = [str(s) for s in final.get("safety", []) if str(s).strip()][:6]
        if not safety and d:
            safety = [f"{h.type}: {h.description}" for h in d.hazards] or [s.caution for s in d.steps if s.caution]
        next_steps = [str(s) for s in final.get("next_steps", []) if str(s).strip()][:8]
        if not next_steps and d:
            next_steps = [s.instruction for s in d.steps]
        summary = str(final.get("summary", "")).strip()
        if not summary:
            summary = f"{d.component}: {d.issue}" if d else "The photo could not be inspected."
        actions = [f"Scheduled '{self.task.title}' ({self.task.priority}) due {self.task.due_date}"] if self.task else []
        return AgentReport(summary=summary[:1500], severity=d.severity if d else "medium", safety=safety,
                           parts=list(self.stock.values()), manual_notes="\n".join(self.manual_notes) or None,
                           actions_taken=actions, next_steps=next_steps)


def _history(run: Run) -> str:
    if not run.steps:
        return "(none yet)"
    return "\n".join(f"{i}. {s.tool} {json.dumps(s.args, ensure_ascii=False)} -> {s.result}"
                     for i, s in enumerate(run.steps, 1))


def _guided(run: Run) -> None:
    """Fixed tool order: used in mock mode and when the model goes off track."""
    if run.diagnosis is None:
        run.call("inspect_image", {}, "Guided: inspect the photo first.")
    d = run.diagnosis
    for part in (d.parts_needed if d else [])[:4]:
        if part not in run.stock:
            run.call("check_inventory", {"part_name": part}, "Guided: check stock for each needed part.")
    if run.asset and run.asset.manual_id and not run.manual_notes and d:
        run.call("query_manual", {"question": f"{d.component}: {d.issue}. What is the procedure and safety?"},
                 "Guided: check the manual.")
    if run.asset and run.task is None and d and d.severity != "low":
        due = {"critical": 0, "high": 2, "medium": 7}[d.severity]
        run.call("schedule_task", {"title": f"{d.component}: {d.issue}"[:120], "priority": d.severity,
                                   "due_in_days": due}, "Guided: schedule the repair.")


def run_agent(image: bytes, mime: str, asset: Optional[Asset] = None, notes: Optional[str] = None) -> AgentDiagnoseResponse:
    run = Run(image, mime, asset, notes)
    if gemma_client.is_mock():
        _guided(run)
        return AgentDiagnoseResponse(report=run.report(), steps=run.steps, mode="mock", diagnosis=run.diagnosis,
                                     task=run.task)

    equipment = "none" if asset is None else " ".join(filter(None, [asset.name, asset.manufacturer, asset.model]))
    manual_note = "" if asset and asset.manual_id else " (No manual is linked: skip this tool.)"
    setting = setting_guidance(setting_key(asset) if asset else None)
    final, misfires = None, 0
    for _ in range(settings.agent_max_steps):
        prompt = AGENT_PROMPT.format(setting=setting, equipment=equipment, notes=notes or "none",
                                     manual_note=manual_note, history=_history(run))
        try:
            reply = gemma_client.generate_json(prompt)
        except gemma_client.GemmaError as e:
            log.warning("Agent step failed: %s", e)
            misfires += 1
            if misfires >= 2:
                break
            continue
        if isinstance(reply.get("final"), dict):
            if run.diagnosis is None:  # never finish without looking at the photo
                run.call("inspect_image", {}, "Inspecting the photo before finishing.")
                continue
            final = reply["final"]
            break
        tool = str(reply.get("tool", "")).strip()
        args = reply.get("args") if isinstance(reply.get("args"), dict) else {}
        before = len(run.calls)
        run.call(tool, args, str(reply.get("thought", "")))
        if len(run.calls) == before or run.steps[-1].result.startswith("Unknown tool"):
            misfires += 1
            if misfires >= 2:
                break

    mode = "agent"
    if final is None:
        mode = "guided"
        _guided(run)
    return AgentDiagnoseResponse(report=run.report(final), steps=run.steps, mode=mode, diagnosis=run.diagnosis,
                                 task=run.task)
