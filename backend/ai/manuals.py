"""Long-Context Manual Assistant: load PDF manuals and answer questions from them.

The whole manual (up to MAX_MANUAL_CHARS) goes into one prompt instead of
chunking/RAG, which leans on Gemma 4's long context window.
"""

import hashlib
import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from api.schemas import ManualAnswer, ManualInfo
from config import settings

from . import gemma_client
from .prompts import MANUAL_PROMPT

log = logging.getLogger(__name__)


class ManualError(ValueError):
    pass


@dataclass
class LoadedManual:
    info: ManualInfo
    text: str
    sha1: str


_manuals: dict[str, LoadedManual] = {}


def _manual_id(filename: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-") or "manual"
    return stem[:40]


def _parse_pdf(data: bytes) -> tuple[str, int]:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [f"[Page {i}]\n{(page.extract_text() or '').strip()}" for i, page in enumerate(reader.pages, start=1)]
    except Exception as e:
        raise ManualError(f"Could not read PDF: {e}") from e
    return "\n\n".join(pages), len(pages)


def add_manual(filename: str, data: bytes) -> ManualInfo:
    text, page_count = _parse_pdf(data)
    if not text.replace("[Page", "").strip(" \n0123456789]"):
        raise ManualError("PDF has no extractable text (scanned images aren't supported yet)")

    truncated = len(text) > settings.max_manual_chars
    if truncated:
        text = text[: settings.max_manual_chars]

    sha1 = hashlib.sha1(data).hexdigest()
    manual_id = _manual_id(filename)
    existing = _manuals.get(manual_id)
    if existing and existing.sha1 != sha1:
        manual_id = f"{manual_id}-{sha1[:6]}"

    info = ManualInfo(id=manual_id, filename=filename, pages=page_count, chars=len(text), truncated=truncated)
    _manuals[manual_id] = LoadedManual(info=info, text=text, sha1=sha1)
    return info


def save_and_add(filename: str, data: bytes) -> ManualInfo:
    """Parse an uploaded manual, then keep a copy so it reloads on restart."""
    info = add_manual(filename, data)
    folder = settings.storage_dir / "manuals"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{info.id}.pdf").write_bytes(data)
    return info


def load_existing() -> None:
    """Load sample manuals from data/manuals/ (read-only) and previously uploaded ones."""
    for folder in (settings.data_dir / "manuals", settings.storage_dir / "manuals"):
        if not folder.is_dir():
            continue
        for pdf in sorted(folder.glob("*.pdf")):
            try:
                add_manual(pdf.name, pdf.read_bytes())
            except ManualError as e:
                log.warning("Skipping manual %s: %s", pdf.name, e)


def list_manuals() -> list[ManualInfo]:
    return [m.info for m in _manuals.values()]


def get_manual(manual_id: str) -> LoadedManual | None:
    return _manuals.get(manual_id)


def ask(manual: LoadedManual, question: str) -> ManualAnswer:
    """Never raises: returns a fallback answer if the model fails."""
    info = manual.info
    if gemma_client.is_mock():
        return ManualAnswer(
            manual_id=info.id,
            question=question,
            answer=(
                f"(Mock answer from {info.filename}.) Set AI_PROVIDER to ollama or google for real answers. "
                f"This manual has {info.pages} pages loaded."
            ),
            pages_cited=[1],
            source="mock",
        )

    prompt = MANUAL_PROMPT.format(filename=info.filename, manual_text=manual.text, question=question)
    try:
        data = gemma_client.generate_json(prompt)
        pages = [int(p) for p in data.get("pages_cited", []) if str(p).isdigit()]
        return ManualAnswer(
            manual_id=info.id,
            question=question,
            answer=str(data.get("answer", "")).strip() or "The model returned an empty answer.",
            pages_cited=[p for p in pages if 1 <= p <= info.pages],
            source="model",
        )
    except gemma_client.GemmaError as e:
        log.warning("Manual query failed: %s", e)
        return ManualAnswer(
            manual_id=info.id,
            question=question,
            answer="The assistant couldn't answer right now. Check the manual's table of contents or try again.",
            source="fallback",
        )
