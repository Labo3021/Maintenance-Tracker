"""Free-form equipment Q&A for the frontend's assistant panel.

Uses the asset's loaded manual when it has one (long-context answer with page
citations); otherwise Gemma answers from general knowledge plus the asset's details.
"""

import logging

from typing import Optional

from api.schemas import Asset, AssistantAnswer

from . import gemma_client, manuals
from .prompts import ASSISTANT_PHOTO_NOTE, ASSISTANT_PROMPT, setting_guidance

log = logging.getLogger(__name__)


def _describe(asset: Asset) -> str:
    lines = [f"- Name: {asset.name}", f"- Category: {asset.category}"]
    for label, value in [("Manufacturer", asset.manufacturer), ("Model", asset.model),
                         ("Serial", asset.serial_number), ("Code", asset.code), ("Location", asset.location),
                         ("Status", asset.status), ("Notes", asset.notes)]:
        if value:
            lines.append(f"- {label}: {value}")
    if asset.quantity_expected is not None and asset.quantity_actual is not None:
        lines.append(f"- Stock: {asset.quantity_actual} of {asset.quantity_expected} units")
    if asset.groups:
        lines.append(f"- Part of: {', '.join(asset.groups)}")
    if asset.difficulty or asset.estimated_minutes:
        lines.append(f"- Usual job: {asset.difficulty or '?'} difficulty, about {asset.estimated_minutes or '?'} minutes")
    if asset.tools_needed:
        lines.append(f"- Tools: {', '.join(asset.tools_needed)}")
    if asset.repair_steps:
        lines.append("- Known procedure: " + " ".join(f"{i}) {s}" for i, s in enumerate(asset.repair_steps, 1)))
    open_tasks = [t for t in asset.tasks if t.status == "open"][:5]
    if open_tasks:
        lines.append("- Open tasks: " + "; ".join(f"{t.title} (due {t.due_date})" for t in open_tasks))
    return "\n".join(lines)


# Categories the frontend uses for everyday items. New assets default to environment="lab",
# so for these the recorded setting is likely just the default: let the model judge instead.
HOME_CATEGORIES = {"appliance", "bicycle", "tool", "other", "refrigerator", "vacuum", "washing_machine",
                   "dryer", "dishwasher", "oven", "microwave", "hvac"}


def setting_key(asset: Asset) -> str:
    """The asset's setting for prompts; 'unknown' when the stored value is probably just the default."""
    if asset.environment == "lab" and asset.category in HOME_CATEGORIES:
        return "unknown"
    return asset.environment


def _setting(asset: Asset) -> str:
    return setting_guidance(setting_key(asset))


def answer(asset: Asset, question: str, image: Optional[bytes] = None, mime_type: str = "image/jpeg") -> AssistantAnswer:
    """Never raises: returns a friendly fallback message if the model fails.
    With a photo, Gemma looks at the image (the manual path is text-only, so it's skipped)."""
    manual = manuals.get_manual(asset.manual_id) if asset.manual_id and not image else None
    if manual:
        result = manuals.ask(manual, question)
        return AssistantAnswer(answer=result.answer, source=result.source, pages_cited=result.pages_cited,
                               used_manual=manual.info.filename)
    if gemma_client.is_mock():
        seen = " I received your photo." if image else ""
        return AssistantAnswer(answer=f"(Mock answer){seen} For {asset.name}: check the manufacturer's manual and "
                                      "power down before any maintenance.", source="mock")
    try:
        prompt = ASSISTANT_PROMPT.format(setting=_setting(asset), equipment=_describe(asset), question=question)
        if image:
            prompt += ASSISTANT_PHOTO_NOTE
        text = gemma_client.generate(prompt, image=image, mime_type=mime_type)
        return AssistantAnswer(answer=text.strip() or "The assistant returned an empty answer.", source="model")
    except gemma_client.GemmaError as e:
        log.warning("Assistant failed: %s", e)
        return AssistantAnswer(answer="The assistant couldn't answer right now. Please try again in a moment.",
                               source="fallback")


def warm_up() -> None:
    """Load the model into memory at startup so the first question doesn't time out."""
    if gemma_client.is_mock():
        return
    try:
        gemma_client.generate("Reply with OK.")
        log.info("Gemma warm-up done")
    except gemma_client.GemmaError as e:
        log.warning("Gemma warm-up failed: %s", e)
