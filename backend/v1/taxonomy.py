"""v1 taxonomy resource: closed domain/area/skill/task-type vocabulary (public).

Curators author questions with the same closed vocabulary surfaced by the
curator UI, so the dropdowns never drift from ``coach/taxonomy.py``. Unlike
``GET /admin/taxonomy`` this endpoint is not admin-gated.

Domains and areas are fixed; signed-in curators may add new **leaf skills**
under an existing area (``POST /taxonomy/skills``). Those are stored in the DB
and merged into the live vocabulary, so they show up in ``tree``/``skills``
here and can be used to tag tasks immediately.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import require_user

router = APIRouter(tags=["v1:taxonomy"])


class SkillCreateRequest(BaseModel):
    skill: str
    area: str


@router.get("/taxonomy", summary="Domain/area/skill + task-type vocabulary")
def taxonomy():
    from coach.taxonomy import AREAS, DOMAINS, LEAF_NODES, TASK_TYPES, TAXONOMY

    return {
        "data": {
            "tree": TAXONOMY,
            "domains": DOMAINS,
            "areas": AREAS,
            "skills": LEAF_NODES,
            "task_types": list(TASK_TYPES),
        }
    }


@router.get("/taxonomy/skills", summary="List curator-added skills")
def list_skills(user: Optional[dict] = Depends(require_user)):
    from coach.custom_skills import list_custom_skills

    return {"data": list_custom_skills()}


@router.post("/taxonomy/skills", status_code=201, summary="Add a custom leaf skill")
def create_skill(req: SkillCreateRequest, user: dict = Depends(require_user)):
    """Register a new leaf skill under an existing area.

    The skill id is canonicalized (lowercase, spaces/dashes -> underscores).
    Rejects an unknown area, a name that collides with an existing node, or a
    malformed name (422).
    """
    from coach.custom_skills import create_custom_skill

    try:
        created = create_custom_skill(
            req.skill, req.area, created_by=user.get("email") or user.get("id") or ""
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"data": created}


@router.delete("/taxonomy/skills/{skill}", summary="Delete a custom leaf skill")
def delete_skill(skill: str, user: dict = Depends(require_user)):
    from coach.custom_skills import delete_custom_skill

    if not delete_custom_skill(skill):
        raise HTTPException(status_code=404, detail="Custom skill not found.")
    return {"data": {"deleted": True, "skill": skill}}
