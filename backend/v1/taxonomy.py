"""v1 taxonomy resource: closed domain/area/skill/task-type vocabulary (public).

Curators author questions with the same closed vocabulary surfaced by the
curator UI, so the dropdowns never drift from ``coach/taxonomy.py``. Unlike
``GET /admin/taxonomy`` this endpoint is not admin-gated.
"""

from fastapi import APIRouter

router = APIRouter(tags=["v1:taxonomy"])


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