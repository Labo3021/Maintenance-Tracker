"""Photo -> new asset draft + maintenance plan + the questions to ask the user."""

import logging
import re
from typing import Optional

from pydantic import ValidationError

from api.schemas import (
    AssetCreate,
    IdentifiedItem,
    IdentifyResult,
    MaintenanceSchedule,
    Question,
    ResultSource,
    ScheduleSuggestion,
)

from api.importer import parse_interval

from . import gemma_client
from .prompts import IDENTIFY_PROMPT, IDENTIFY_RETRY_SUFFIX

log = logging.getLogger(__name__)

MOCK_ITEM = IdentifiedItem(
    name="French-door refrigerator",
    category="refrigerator",
    environment="household",
    manufacturer="Samsung",
    model=None,
    confidence=0.9,
    maintenance_plan=[
        ScheduleSuggestion(title="Replace water filter", kind="replace", interval_days=180,
                           notes="Filter housing is usually top-right inside the fridge."),
        ScheduleSuggestion(title="Clean condenser coils", kind="clean", interval_days=180,
                           notes="Unplug first; coils are behind the bottom front grille or at the back."),
        ScheduleSuggestion(title="Inspect door gaskets", kind="inspect", interval_days=90,
                           notes="Close the door on a sheet of paper; if it slides out easily, the seal is weak."),
        ScheduleSuggestion(title="Check fridge and freezer temperatures", kind="inspect", interval_days=30,
                           notes="Fridge 37-40°F (3-4°C), freezer 0°F (-18°C)."),
    ],
)

FALLBACK_ITEM = IdentifiedItem(name="Unidentified item", category="general", confidence=0.0, maintenance_plan=[
    ScheduleSuggestion(title="General inspection", kind="inspect", interval_days=180,
                       notes="Automatic identification failed; edit this plan to match the item."),
])

# Where people usually find the model/serial label, by category.
LABEL_HINTS = {
    "refrigerator": "Usually on a sticker inside the fridge, on a side wall or under the crisper drawer.",
    "washing_machine": "Usually inside the door rim or on the back panel.",
    "dryer": "Usually inside the door opening.",
    "dishwasher": "Usually on the edge of the door or the tub frame.",
    "vacuum": "Usually on the underside or behind the dust bin.",
    "hvac": "On the unit's data plate, often on the side panel.",
    "oven": "Usually behind the drawer or on the door frame.",
    "microwave": "Usually inside the door frame or on the back.",
}


# Typical intervals for common jobs. Used to catch unit mistakes from the model
# (e.g. "clean condenser coils every 6 days"), not to replace its judgement.
TYPICAL_INTERVALS: list[tuple[str, int]] = [
    (r"condenser coil", 180), (r"water filter", 180), (r"(door )?gasket|door seal", 180),
    (r"(hvac|furnace|air|ac) filter", 90), (r"dryer (vent|duct)|lint (duct|vent)", 365),
    (r"smoke (detector|alarm).*batter|batter.*smoke", 365), (r"smoke (detector|alarm)", 30),
    (r"carbon monoxide|co detector", 30), (r"dishwasher filter", 30), (r"descal", 90),
    (r"range hood|grease filter", 90), (r"water heater", 365), (r"vacuum filter|hepa", 90),
    (r"brush ?roll", 30), (r"defrost", 180), (r"ice maker", 180),
]


def _sane_interval(s: ScheduleSuggestion) -> int:
    days = s.interval_days
    if s.frequency:
        try:
            days = parse_interval(s.frequency, "")
        except ValueError:
            pass
    title = s.title.lower()
    for pattern, typical in TYPICAL_INTERVALS:
        if re.search(pattern, title):
            if not typical / 3 <= days <= typical * 3:
                log.info("Interval for '%s' looked wrong (%d days); using %d", s.title, days, typical)
                days = typical
            break
    return days


def _questions(item: IdentifiedItem, draft: AssetCreate) -> list[Question]:
    hint = LABEL_HINTS.get(item.category, "Look for a sticker or metal plate on the back, bottom or inside the door.")
    qs: list[Question] = []
    if not item.manufacturer:
        qs.append(Question(target="manufacturer", prompt="What brand is it?", type="text"))
    if not item.model:
        qs.append(Question(target="model", prompt="What's the model number?", type="text",
                           hint=hint + " Needed to find the manual."))
    if not item.serial_number:
        qs.append(Question(target="serial_number", prompt="Serial number (optional)", type="text", hint=hint))
    qs.append(Question(target="location", prompt="Where is it?", type="text",
                       hint="e.g. Kitchen, Garage, Lab 204"))
    for i, s in enumerate(draft.schedules):
        qs.append(Question(
            target=f"schedules.{i}.last_done",
            prompt=f"When was the last time you did this: {s.title.lower()}?",
            type="date",
            hint="Leave empty if you don't know; the first reminder will be due today.",
        ))
    return qs


def _draft(item: IdentifiedItem) -> AssetCreate:
    return AssetCreate(
        name=item.name,
        category=item.category,
        environment=item.environment,
        manufacturer=item.manufacturer,
        model=item.model,
        serial_number=item.serial_number,
        schedules=[
            MaintenanceSchedule(**(s.model_dump(exclude={"frequency"}) | {"interval_days": _sane_interval(s)}))
            for s in item.maintenance_plan
        ],
    )


def identify_image(image: bytes, mime_type: str, notes: Optional[str] = None) -> IdentifyResult:
    """Never raises: returns a generic, editable draft if the model fails twice."""
    item, source = _identify(image, mime_type, notes)
    draft = _draft(item)
    return IdentifyResult(draft=draft, questions=_questions(item, draft), confidence=item.confidence, source=source)


def _identify(image: bytes, mime_type: str, notes: Optional[str]) -> tuple[IdentifiedItem, ResultSource]:
    if gemma_client.is_mock():
        return MOCK_ITEM, "mock"
    prompt = IDENTIFY_PROMPT.format(context=f"User notes: {notes}\n" if notes else "")
    error = ""
    for attempt in range(2):
        try:
            text = prompt + (IDENTIFY_RETRY_SUFFIX.format(error=error) if error else "")
            item = IdentifiedItem.model_validate(gemma_client.generate_json(text, image=image, mime_type=mime_type))
            # Small models sometimes return "null"/"unknown" strings instead of null.
            for f in ("manufacturer", "model", "serial_number"):
                v = getattr(item, f)
                if v and v.strip().lower() in ("null", "none", "unknown", "n/a", ""):
                    setattr(item, f, None)
            item.category = item.category.strip().lower().replace(" ", "_") or "general"
            return item, "model"
        except ValidationError as e:
            error = str(e)[:500]
            log.warning("Identify JSON invalid (attempt %d): %s", attempt + 1, error)
        except gemma_client.GemmaError as e:
            error = str(e)
            log.warning("Identify failed (attempt %d): %s", attempt + 1, error)
    return FALLBACK_ITEM, "fallback"
