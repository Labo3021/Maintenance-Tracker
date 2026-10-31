"""Find, download and load an equipment's manual.

Gemma runs offline, so the web part is plain HTTP:
- Always: build a search link the user can open.
- With SEARCH_PROVIDER=brave: search, rank results (PDFs, model number, maker's
  domain), download the best PDF, check the model number appears inside it, and
  load it into the manual assistant.
Only the brand/model text is sent to the search provider, never photos.
"""

import logging
import re
from typing import Optional
from urllib.parse import quote_plus, unquote, urlparse

import httpx

from api.schemas import Asset, ManualCandidate, ManualInfo
from config import settings

from . import manuals

log = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 30
MAX_CANDIDATES = 8
MAX_DOWNLOAD_TRIES = 3
USER_AGENT = "Mozilla/5.0 (LabGuard AI manual finder)"


class SearchError(RuntimeError):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def build_query(asset: Asset) -> str:
    terms = [asset.manufacturer, asset.model] if asset.model else [asset.manufacturer, asset.name]
    return " ".join(filter(None, terms)) + " user manual pdf"


def search_url(query: str) -> str:
    return "https://www.google.com/search?q=" + quote_plus(query)


def _brave_search(query: str) -> list[dict]:
    if not settings.brave_api_key:
        raise SearchError("SEARCH_PROVIDER=brave but BRAVE_API_KEY is not set")
    try:
        r = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 20},
            headers={"Accept": "application/json", "X-Subscription-Token": settings.brave_api_key},
            timeout=15,
        )
        r.raise_for_status()
        return [{"title": x.get("title", ""), "url": x["url"]} for x in r.json().get("web", {}).get("results", [])]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise SearchError(f"Brave search failed: {e}") from e


def search(query: str) -> list[dict]:
    if settings.search_provider == "brave":
        return _brave_search(query)
    raise SearchError(f"Unknown SEARCH_PROVIDER '{settings.search_provider}'")


def rank(results: list[dict], asset: Asset) -> list[ManualCandidate]:
    model = _norm(asset.model or "")
    maker = _norm(asset.manufacturer or "")
    out = []
    for r in results:
        url, title = r["url"], r.get("title", "")
        host = urlparse(url).hostname or ""
        haystack = _norm(unquote(url) + title)
        is_pdf = urlparse(url).path.lower().endswith(".pdf")
        score = (
            3 * is_pdf
            + (3 if model and model in haystack else 0)
            + (2 if maker and maker in _norm(host) else 0)
            + (1 if "manual" in haystack or "guide" in haystack else 0)
        )
        out.append(ManualCandidate(title=title or url, url=url, is_pdf=is_pdf, score=score))
    return sorted(out, key=lambda c: -c.score)[:MAX_CANDIDATES]


def download_pdf(url: str) -> Optional[bytes]:
    """Return the PDF bytes, or None if the URL isn't a PDF / is too big / fails."""
    if urlparse(url).scheme not in ("http", "https"):
        return None
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT,
                          headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > settings.max_pdf_bytes:
                    log.info("Skipping %s: larger than MAX_PDF_MB", url)
                    return None
                if len(data) >= 5 and not data.startswith(b"%PDF"):
                    return None  # an HTML page, not a PDF
            return bytes(data) if data.startswith(b"%PDF") else None
    except httpx.HTTPError as e:
        log.info("Download failed for %s: %s", url, e)
        return None


def _filename(url: str, asset: Asset) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    if name.lower().endswith(".pdf") and len(name) > 4:
        return name
    return f"{asset.manufacturer or ''} {asset.model or asset.name} manual.pdf".strip()


def load_from_url(url: str, asset: Asset) -> tuple[Optional[ManualInfo], bool]:
    """Download + load a manual. Returns (info or None, verified)."""
    data = download_pdf(url)
    if data is None:
        return None, False
    try:
        info = manuals.save_and_add(_filename(url, asset), data)
    except manuals.ManualError as e:
        log.info("Downloaded PDF unusable (%s): %s", url, e)
        return None, False
    loaded = manuals.get_manual(info.id)
    verified = bool(asset.model) and loaded is not None and _norm(asset.model) in _norm(loaded.text)
    return info, verified
