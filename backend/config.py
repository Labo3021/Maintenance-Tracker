"""Runtime settings, read from .env (repo root, then backend/) and the environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent

load_dotenv(REPO_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _path(value: str) -> Path:
    """Resolve paths relative to backend/ so `DATA_DIR=../data` works from anywhere."""
    p = Path(value)
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


class Settings:
    def __init__(self) -> None:
        # "mock" returns canned responses so the frontend can build before the model is ready.
        self.ai_provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
        self.gemma_model = os.getenv("GEMMA_MODEL", "").strip()
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        # Ollama's default context is small and silently truncates long prompts (manuals).
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
        self.google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        self.ai_timeout_seconds = float(os.getenv("AI_TIMEOUT_SECONDS", "120"))

        self.backend_port = int(os.getenv("BACKEND_PORT", "8000"))
        self.cors_origins = [
            o.strip()
            for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        ]

        # data/ is read-only for the backend: seed inventory + sample manuals.
        self.data_dir = _path(os.getenv("DATA_DIR", "../data"))
        # Everything the backend writes lives here (gitignored).
        self.storage_dir = _path(os.getenv("STORAGE_DIR", "storage"))

        self.max_image_bytes = int(os.getenv("MAX_IMAGE_MB", "10")) * 1024 * 1024
        self.max_pdf_bytes = int(os.getenv("MAX_PDF_MB", "50")) * 1024 * 1024
        # ~4 chars/token, so 400k chars is roughly 100k tokens of manual text.
        self.max_manual_chars = int(os.getenv("MAX_MANUAL_CHARS", "400000"))


settings = Settings()
