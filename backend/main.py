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

from backend.routes import router
from backend.admin_routes import admin_router
from backend.admin_page import admin_page_router

app = FastAPI(title="AI Research Coach API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(admin_router)
app.include_router(admin_page_router)


@app.get("/health")
def health():
    return {"status": "ok"}
