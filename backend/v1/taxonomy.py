"""v1 taxonomy resource: closed tag/family/task-type vocabulary (public).

Curators author questions with the same closed vocabulary as the admin seed
form, so the dropdowns never drift from ``coach/taxonomy.py``. Unlike
``GET /admin/taxonomy`` this endpoint is not admin-gated.
"""

from fastapi import APIRouter

router = APIRouter(tags=["v1:taxonomy"])


@router.get("/taxonomy", summary="Tag/family/task-type vocabulary")
def taxonomy():
    from coach.taxonomy import FAMILIES, TAGS, TASK_TYPES

    return {
        "data": {
            "families": FAMILIES,
            "tags": TAGS,
            "task_types": list(TASK_TYPES),
        }
    }