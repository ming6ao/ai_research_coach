"""v1 user resources: identity, own sessions, own data wipe.

- GET    /api/v1/me           -> {data: user} (requires auth)
- GET    /api/v1/me/sessions  -> {data: [{id, candidate, done, updated_at}], meta}
- DELETE /api/v1/me/data      -> {data: {deleted, deleted_by_table}}
"""

from typing import Optional

from fastapi import APIRouter, Depends

from backend.auth import get_current_user, require_user
from backend.dependencies import get_store
from backend.v1.pagination import PageParams, paginate

router = APIRouter(tags=["v1:users"])


@router.get("/me", summary="Current user")
def get_me(user: dict = Depends(require_user)):
    return {"data": user}


@router.get("/me/sessions", summary="List my sessions")
def list_my_sessions(
    page: PageParams = Depends(), user: Optional[dict] = Depends(get_current_user)
):
    from coach.selection import pick_next_task
    from coach.session import Session

    if user is None:
        return {"data": [], "meta": {"page": page.page, "page_size": page.page_size, "total": 0}}
    candidate = user["email"]
    store = get_store()

    sessions = []
    for s in store.list_by_candidate(candidate):
        state = store.get(s["session_id"])
        done = False
        if state and "session" in state:
            session = Session.from_dict(state["session"])
            try:
                done = pick_next_task(candidate, session) is None
            except Exception:
                done = session.index >= len(session.tasks)
        sessions.append({
            "id": s["session_id"],
            "candidate": s["candidate"],
            "done": done,
            "updated_at": s["updated_at"],
        })
    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    items, meta = paginate(sessions, page.page, page.page_size)
    return {"data": items, "meta": meta}


@router.delete("/me/data", summary="Delete all my data")
def delete_my_data(user: dict = Depends(require_user)):
    from coach.admin import clear_candidate_everything

    result = clear_candidate_everything(user["email"])
    return {
        "data": {
            "deleted": result["deleted"]["total"],
            "deleted_by_table": result["deleted"],
        }
    }
