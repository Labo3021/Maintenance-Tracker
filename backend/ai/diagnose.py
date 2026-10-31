"""Visual Equipment Inspector: photo -> validated DiagnosisResult."""

import logging
from typing import Optional

from pydantic import ValidationError

from api.schemas import DiagnosisResult, RepairStep, ResultSource, SafetyHazard

from . import gemma_client
from .prompts import DIAGNOSE_PROMPT, DIAGNOSE_RETRY_SUFFIX

log = logging.getLogger(__name__)

MOCK_DIAGNOSIS = DiagnosisResult(
    component="Centrifuge lid gasket",
    issue="Cracked and flattened rubber seal around the lid; possible aerosol leak during runs.",
    severity="high",
    confidence=0.82,
    hazards=[
        SafetyHazard(type="biohazard", description="Aerosols may escape if biological samples were spun."),
        SafetyHazard(type="mechanical", description="Do not open the lid while the rotor is moving."),
    ],
    tools=["Nitrile gloves", "70% ethanol or approved disinfectant", "Plastic pry tool", "Lint-free wipes"],
    parts_needed=["Replacement lid gasket (OEM part for this model)"],
    steps=[
        RepairStep(step=1, instruction="Stop the centrifuge, unplug it, and wait for the rotor to stop fully.",
                   caution="Never open the lid while the rotor is spinning."),
        RepairStep(step=2, instruction="Decontaminate the chamber and lid with approved disinfectant.",
                   caution="Wear gloves and eye protection; treat residue as biohazardous."),
        RepairStep(step=3, instruction="Pry the old gasket out of its groove with a plastic tool."),
        RepairStep(step=4, instruction="Clean the groove and press the new gasket in evenly, starting at the hinge."),
        RepairStep(step=5, instruction="Close the lid and confirm it latches; run an empty test cycle."),
    ],
    requires_technician=False,
)

FALLBACK_DIAGNOSIS = DiagnosisResult(
    component="Unknown",
    issue="Automatic diagnosis is unavailable right now. Inspect manually before using the equipment.",
    severity="medium",
    confidence=0.0,
    hazards=[SafetyHazard(type="unknown", description="Hazards could not be assessed from the photo.")],
    tools=[],
    parts_needed=[],
    steps=[
        RepairStep(step=1, instruction="Power down and isolate the equipment.",
                   caution="Follow your lab's lockout/tagout and decontamination procedures."),
        RepairStep(step=2, instruction="Check the equipment manual's troubleshooting section."),
        RepairStep(step=3, instruction="Contact the lab manager or manufacturer service if unsure."),
    ],
    requires_technician=True,
)


def diagnose_image(
    image: bytes,
    mime_type: str,
    equipment_hint: Optional[str] = None,
    notes: Optional[str] = None,
) -> tuple[DiagnosisResult, ResultSource]:
    """Never raises: returns the fallback diagnosis if the model fails twice."""
    if gemma_client.is_mock():
        return MOCK_DIAGNOSIS, "mock"

    context = ""
    if equipment_hint:
        context += f"Equipment: {equipment_hint}\n"
    if notes:
        context += f"User notes: {notes}\n"
    prompt = DIAGNOSE_PROMPT.format(context=context)

    error = ""
    for attempt in range(2):
        try:
            text = prompt + (DIAGNOSE_RETRY_SUFFIX.format(error=error) if error else "")
            data = gemma_client.generate_json(text, image=image, mime_type=mime_type)
            return DiagnosisResult.model_validate(data), "model"
        except ValidationError as e:
            error = str(e)[:500]
            log.warning("Diagnosis JSON invalid (attempt %d): %s", attempt + 1, error)
        except gemma_client.GemmaError as e:
            error = str(e)
            log.warning("Diagnosis failed (attempt %d): %s", attempt + 1, error)
    return FALLBACK_DIAGNOSIS, "fallback"
