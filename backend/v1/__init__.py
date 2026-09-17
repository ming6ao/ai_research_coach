"""Canonical v1 API (REST resources + {data, meta} envelopes).

Mounts under ``/api/v1``; see submodules for endpoint details.
"""

from fastapi import APIRouter

from backend.v1.sessions import router as sessions_router
from backend.v1.shares import router as shares_router
from backend.v1.tasks import router as tasks_router
from backend.v1.taxonomy import router as taxonomy_router
from backend.v1.users import router as users_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(sessions_router)
v1_router.include_router(shares_router)
v1_router.include_router(tasks_router)
v1_router.include_router(taxonomy_router)
v1_router.include_router(users_router)
