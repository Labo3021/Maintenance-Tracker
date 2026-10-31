"""One interface to Gemma 4, whether it runs locally (Ollama) or in Google AI Studio.

Pick the provider with AI_PROVIDER in .env: "ollama", "google", or "mock".
"""

import base64
import json
import re
from typing import Optional

import httpx

from config import settings


class GemmaError(RuntimeError):
    """The model couldn't be reached or returned something unusable."""


def is_mock() -> bool:
    return settings.ai_provider == "mock"


def generate(prompt: str, image: Optional[bytes] = None, mime_type: str = "image/jpeg", json_mode: bool = False) -> str:
    """Send a prompt (and optionally one image) to Gemma and return the raw text reply."""
    if not settings.gemma_model:
        raise GemmaError("GEMMA_MODEL is not set in .env")
    if settings.ai_provider == "ollama":
        return _ollama(prompt, image, json_mode)
    if settings.ai_provider == "google":
        return _google(prompt, image, mime_type)
    raise GemmaError(f"Unknown AI_PROVIDER '{settings.ai_provider}' (use ollama, google, or mock)")


def generate_json(prompt: str, image: Optional[bytes] = None, mime_type: str = "image/jpeg") -> dict:
    """Like generate(), but parses the reply as a JSON object."""
    return extract_json(generate(prompt, image, mime_type, json_mode=True))


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a reply, tolerating ```json fences and chatter."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise GemmaError(f"Model did not return valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise GemmaError("Model returned JSON that is not an object")
    return data


def _ollama(prompt: str, image: Optional[bytes], json_mode: bool) -> str:
    message: dict = {"role": "user", "content": prompt}
    if image:
        message["images"] = [base64.b64encode(image).decode()]
    body: dict = {
        "model": settings.gemma_model,
        "messages": [message],
        "stream": False,
        "think": False,  # skip reasoning traces: faster, and keeps JSON replies clean
        "keep_alive": "30m",  # stay loaded between requests (reloading takes ~40 s)
        "options": {"num_ctx": settings.ollama_num_ctx},
    }
    if json_mode:
        body["format"] = "json"
    try:
        r = httpx.post(f"{settings.ollama_host}/api/chat", json=body, timeout=settings.ai_timeout_seconds)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise GemmaError(f"Ollama request failed: {e}") from e


_google_client = None


def _google(prompt: str, image: Optional[bytes], mime_type: str) -> str:
    global _google_client
    if not settings.google_api_key:
        raise GemmaError("GOOGLE_API_KEY is not set in .env")
    try:
        from google import genai
        from google.genai import types

        if _google_client is None:
            _google_client = genai.Client(
                api_key=settings.google_api_key,
                http_options=types.HttpOptions(timeout=int(settings.ai_timeout_seconds * 1000)),
            )
        contents: list = [prompt]
        if image:
            contents.insert(0, types.Part.from_bytes(data=image, mime_type=mime_type))
        response = _google_client.models.generate_content(model=settings.gemma_model, contents=contents)
        if not response.text:
            raise GemmaError("Google AI Studio returned an empty response")
        return response.text
    except GemmaError:
        raise
    except Exception as e:  # SDK raises several error types; surface them all the same way
        raise GemmaError(f"Google AI Studio request failed: {e}") from e
