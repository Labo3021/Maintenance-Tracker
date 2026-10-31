"""LabGuard AI backend. Run from backend/:  uvicorn main:app --reload"""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai import assistant, manuals
from api.routes import router
from config import settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manuals.load_existing()
    threading.Thread(target=assistant.warm_up, daemon=True).start()
    yield


app = FastAPI(
    title="LabGuard AI API",
    description="Lab equipment diagnosis, inventory scheduling and manual Q&A powered by Gemma 4.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    return {
        "status": "ok",
        "ai_provider": settings.ai_provider,
        "model": settings.gemma_model or None,
        "manuals_loaded": len(manuals.list_manuals()),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.backend_port, reload=True)
