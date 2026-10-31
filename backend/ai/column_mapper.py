"""Ask Gemma which asset field an unrecognized spreadsheet column holds.

Only headers plus up to 3 sample values per column are sent, never the whole sheet.
"""

import json
import logging

from api.schemas import ResultSource

from . import gemma_client
from .prompts import COLUMN_MAPPING_PROMPT

log = logging.getLogger(__name__)


def map_unknown_headers(
    columns: dict[str, list[str]], fields: dict[str, str]
) -> tuple[dict[str, str | None], ResultSource]:
    """Returns ({header: field or None}, source). Never raises; on failure maps nothing."""
    if gemma_client.is_mock():
        return {}, "mock"
    prompt = COLUMN_MAPPING_PROMPT.format(
        fields="\n".join(f'- "{f}": {d}' for f, d in fields.items()),
        columns=json.dumps(columns, indent=2, ensure_ascii=False),
    )
    try:
        data = gemma_client.generate_json(prompt)
    except gemma_client.GemmaError as e:
        log.warning("Column mapping failed: %s", e)
        return {}, "fallback"
    mapping = data.get("mapping", data)
    if not isinstance(mapping, dict):
        return {}, "fallback"
    return {str(h): (f if isinstance(f, str) and f in fields else None) for h, f in mapping.items()}, "model"
