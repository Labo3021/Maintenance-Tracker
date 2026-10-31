"""Free-form equipment Q&A for the frontend's assistant panel.

Uses the asset's loaded manual when it has one (long-context answer with page
citations); otherwise Gemma answers from general knowledge plus the asset's details.
"""

import logging

from api.schemas import Asset, AssistantAnswer

from . import gemma_client, manuals
from .prompts import ASSISTANT_PROMPT

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
    open_tasks = [t for t in asset.tasks if t.status == "open"][:5]
    if open_tasks:
        lines.append("- Open tasks: " + "; ".join(f"{t.title} (due {t.due_date})" for t in open_tasks))
    return "\n".join(lines)


def answer(asset: Asset, question: str) -> AssistantAnswer:
    """Never raises: returns a friendly fallback message if the model fails."""
    manual = manuals.get_manual(asset.manual_id) if asset.manual_id else None
    if manual:
        result = manuals.ask(manual, question)
        return AssistantAnswer(answer=result.answer, source=result.source, pages_cited=result.pages_cited,
                               used_manual=manual.info.filename)
    if gemma_client.is_mock():
        return AssistantAnswer(answer=f"(Mock answer) For {asset.name}: check the manufacturer's manual and "
                                      "power down before any maintenance.", source="mock")
    try:
        text = gemma_client.generate(ASSISTANT_PROMPT.format(equipment=_describe(asset), question=question))
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
