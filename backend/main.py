"""FastAPI application entry point.

Run with:
    cd /path/to/ai_research_coach
    uvicorn backend.main:app --reload --port 8001
"""

import sys
from pathlib import Path

# Ensure project root is importable
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv(_root / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth_routes import router as auth_router
from backend.admin_routes import admin_router
from backend.v1 import v1_router

import os

app = FastAPI(title="AI Research Coach API", version="1.0.0")


def _cors_origins() -> list[str]:
    """Env-driven CORS: FRONTEND_URL plus comma-separated CORS_ORIGINS."""
    origins = {"http://localhost:5173", "http://localhost:3000"}
    frontend_url = os.getenv("FRONTEND_URL", "").strip()
    if frontend_url:
        origins.add(frontend_url.rstrip("/"))
    for extra in os.getenv("CORS_ORIGINS", "").split(","):
        extra = extra.strip().rstrip("/")
        if extra:
            origins.add(extra)
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(v1_router)
app.include_router(admin_router)


@app.get("/health", tags=["health"], summary="Liveness probe (legacy alias)")
def health():
    return {"status": "ok"}


@app.get("/healthz", tags=["health"], summary="Liveness probe")
def healthz():
    return {"status": "ok"}
