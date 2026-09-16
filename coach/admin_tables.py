"""Generic admin table browser: metadata + paginated/searchable rows + edit/delete.

Covers all 6 stored tables (``users``, ``auth_tokens``, ``active_sessions``,
``tasks``, ``task_attempts``, ``user_skill_beliefs``). All helpers here assume
the caller already enforced the ``ADMIN_EMAILS`` allowlist — every route that
uses this module must depend on an admin-only guard.

Conventions:
- ``list_rows`` returns list-view dicts (long/JSON blobs truncated) plus a
  total count so the UI can paginate server-side.
- ``get_row`` returns the full row for the detail drawer / edit modal.
- ``update_row`` only touches whitelisted editable columns and validates
  types/ranges; it returns the full updated row.
- ``delete_row`` deletes one row (tasks cascade to their attempts via
  ``coach.tasks.delete_task``) and returns deleted counts.
- Sensitive values (``users.password_hash``) are never returned. Tokens and
  session JSON are returned in full to admins (the UI masks them); list views
  truncate them to previews.
"""

from __future__ import annotations

import json
from typing import Any, Optional

LIST_PREVIEW_LEN = 200

TABLE_NAMES = (
    "users",
    "auth_tokens",
    "active_sessions",
    "tasks",
    "session_steps",
    "user_skill_beliefs",
)

# Per-table registry: pk, columns (name/type/searchable/editable), defaults.
# ``kind`` is informational for the UI (text/number/bool/datetime/json).
TABLE_REGISTRY: dict[str, dict[str, Any]] = {
    "users": {
        "pk": "id",
        "default_sort": "created_at",
        "columns": [
            {"name": "id", "kind": "text", "searchable": True, "editable": False},
            {"name": "email", "kind": "text", "searchable": True, "editable": False},
            {"name": "display_name", "kind": "text", "searchable": True, "editable": True},
            {"name": "created_at", "kind": "datetime", "searchable": False, "editable": False},
        ],
    },
    "auth_tokens": {
        "pk": "token",
        "default_sort": "created_at",
        "columns": [
            {"name": "token", "kind": "text", "searchable": False, "editable": False, "sensitive": True},
            {"name": "user_id", "kind": "text", "searchable": True, "editable": False},
            {"name": "created_at", "kind": "datetime", "searchable": False, "editable": False},
            {"name": "expires_at", "kind": "datetime", "searchable": False, "editable": False},
        ],
    },
    "active_sessions": {
        "pk": "session_id",
        "default_sort": "updated_at",
        "columns": [
            {"name": "session_id", "kind": "text", "searchable": True, "editable": False},
            {"name": "candidate", "kind": "text", "searchable": True, "editable": False},
            {"name": "status", "kind": "text", "searchable": False, "editable": False},
            {"name": "session_json", "kind": "json", "searchable": False, "editable": False},
            {"name": "resumed_from_share", "kind": "text", "searchable": False, "editable": False},
            {"name": "fork_of", "kind": "text", "searchable": False, "editable": False},
            {"name": "updated_at", "kind": "datetime", "searchable": False, "editable": False},
        ],
    },
    "tasks": {
        "pk": "id",
        "default_sort": "created_at",
        "columns": [
            {"name": "id", "kind": "text", "searchable": True, "editable": False},
            {"name": "source", "kind": "text", "searchable": True, "editable": False},
            {"name": "owner", "kind": "text", "searchable": True, "editable": False},
            {"name": "prompt", "kind": "text", "searchable": True, "editable": True},
            {"name": "scaffold", "kind": "text", "searchable": False, "editable": True},
            {"name": "difficulty", "kind": "number", "searchable": False, "editable": True},
            {"name": "max_score", "kind": "number", "searchable": False, "editable": True},
            {"name": "parts_json", "kind": "json", "searchable": False, "editable": True},
            {"name": "context_notes", "kind": "text", "searchable": True, "editable": True},
            {"name": "tags_json", "kind": "json", "searchable": False, "editable": True},
            {"name": "task_type", "kind": "text", "searchable": False, "editable": True},
            {"name": "parent_task_id", "kind": "text", "searchable": False, "editable": False},
            {"name": "target_text", "kind": "text", "searchable": False, "editable": False},
            {"name": "version_index", "kind": "number", "searchable": False, "editable": True},
            {"name": "depends_on_task_id", "kind": "text", "searchable": True, "editable": True},
            {"name": "version_root_id", "kind": "text", "searchable": False, "editable": True},
            {"name": "is_public", "kind": "bool", "searchable": False, "editable": True},
            {"name": "created_at", "kind": "datetime", "searchable": False, "editable": False},
        ],
    },
    "session_steps": {
        "pk": "id",
        "default_sort": "created_at",
        "columns": [
            {"name": "id", "kind": "text", "searchable": True, "editable": False},
            {"name": "session_id", "kind": "text", "searchable": True, "editable": False},
            {"name": "candidate", "kind": "text", "searchable": True, "editable": False},
            {"name": "step_index", "kind": "number", "searchable": False, "editable": False},
            {"name": "task_id", "kind": "text", "searchable": True, "editable": False},
            {"name": "role", "kind": "text", "searchable": False, "editable": False},
            {"name": "reward", "kind": "number", "searchable": False, "editable": False},
            {"name": "inherited", "kind": "bool", "searchable": False, "editable": False},
            {"name": "created_at", "kind": "datetime", "searchable": False, "editable": False},
        ],
    },
    "user_skill_beliefs": {
        "pk": "id",
        "default_sort": "updated_at",
        "columns": [
            {"name": "id", "kind": "text", "searchable": False, "editable": False},
            {"name": "candidate", "kind": "text", "searchable": True, "editable": False},
            {"name": "level", "kind": "text", "searchable": False, "editable": False},
            {"name": "key", "kind": "text", "searchable": False, "editable": False},
            {"name": "mean", "kind": "number", "searchable": False, "editable": True},
            {"name": "variance", "kind": "number", "searchable": False, "editable": True},
            {"name": "questions_answered", "kind": "number", "searchable": False, "editable": True},
            {"name": "updated_at", "kind": "datetime", "searchable": False, "editable": False},
        ],
    },
}

# Extra exact-match filters the UI may pass per table (besides free-text q).
FILTERABLE = {
    "tasks": ("owner",),
    "session_steps": ("candidate", "task_id", "session_id"),
    "user_skill_beliefs": ("candidate",),
    "active_sessions": ("candidate",),
    "auth_tokens": ("user_id",),
    "users": ("email",),
}


def _registry(name: str) -> dict[str, Any]:
    reg = TABLE_REGISTRY.get(name)
    if reg is None:
        raise KeyError(f"Unknown table: {name}")
    return reg


def _preview(value: Any, limit: int = LIST_PREVIEW_LEN) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def list_tables() -> list[dict[str, Any]]:
    """Table metadata + live row counts for the admin nav."""
    from coach.db import create_schema

    create_schema()
    out = []
    for name in TABLE_NAMES:
        reg = TABLE_REGISTRY[name]
        out.append(
            {
                "name": name,
                "pk": reg["pk"],
                "default_sort": reg["default_sort"],
                "columns": reg["columns"],
                "count": count_rows(name),
            }
        )
    return out


def count_rows(name: str, q: Optional[str] = None, filters: Optional[dict] = None) -> int:
    """Row count for a table, honoring the same search/filters as list_rows."""
    _registry(name)
    if name in ("tasks", "task_attempts", "user_skill_beliefs"):
        return _count_orm_rows(name, q=q, filters=filters)
    return _count_raw_rows(name, q=q, filters=filters)


def list_rows(
    name: str,
    page: int = 1,
    page_size: int = 25,
    q: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = "desc",
    filters: Optional[dict] = None,
) -> dict[str, Any]:
    """Paginated, searchable row listing (list-view truncation applied)."""
    reg = _registry(name)
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 25)))
    order = "asc" if (order or "").lower() == "asc" else "desc"
    col_names = {c["name"] for c in reg["columns"]}
    sort = sort if sort in col_names else reg["default_sort"]
    filters = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
    allowed_filters = set(FILTERABLE.get(name, ()))
    filters = {k: v for k, v in filters.items() if k in allowed_filters}

    if name in ("tasks", "session_steps", "user_skill_beliefs"):
        rows, total = _list_orm_rows(name, page, page_size, q, sort, order, filters)
    else:
        rows, total = _list_raw_rows(name, page, page_size, q, sort, order, filters)
    return {"rows": rows, "total": total, "page": page, "page_size": page_size}


def get_row(name: str, row_id: str) -> Optional[dict[str, Any]]:
    """Full row by primary key (no truncation)."""
    _registry(name)
    if name in ("tasks", "session_steps", "user_skill_beliefs"):
        return _get_orm_row(name, row_id)
    return _get_raw_row(name, row_id)


def update_row(name: str, row_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Validate + apply an admin edit; returns the full updated row."""
    reg = _registry(name)
    editable = {c["name"] for c in reg["columns"] if c.get("editable")}
    unknown = set(fields or {}) - editable
    if unknown:
        raise ValueError(f"Not editable for {name}: {sorted(unknown)}")
    if not fields:
        raise ValueError("No editable fields provided.")
    if name == "tasks":
        return _update_task(row_id, fields)
    if name == "session_steps":
        return _update_step(row_id, fields)
    if name == "user_skill_beliefs":
        return _update_belief(row_id, fields)
    if name == "users":
        return _update_user(row_id, fields)
    raise ValueError(f"Table {name} is read-only (delete only).")


def delete_row(name: str, row_id: str) -> dict[str, Any]:
    """Delete one row; returns ``{"deleted": n, ...}`` detail."""
    _registry(name)
    if name == "tasks":
        from coach.tasks import delete_task, get_task

        if get_task(row_id) is None:
            return {"deleted": 0}
        result = delete_task(row_id)
        return {"deleted": result.get("deleted_task", 0), **result}
    if name in ("session_steps", "user_skill_beliefs"):
        return {"deleted": _delete_orm_row(name, row_id)}
    return _delete_raw_row(name, row_id)


# --- ORM tables (tasks / task_attempts / user_skill_beliefs) ---


def _orm_model(name: str):
    from coach.steps import SessionStepModel
    from coach.tasks import SkillBeliefModel, TaskModel

    return {
        "tasks": TaskModel,
        "session_steps": SessionStepModel,
        "user_skill_beliefs": SkillBeliefModel,
    }[name]


def _orm_search_cols(name: str):
    from coach.steps import SessionStepModel
    from coach.tasks import SkillBeliefModel, TaskModel

    return {
        "tasks": (TaskModel.prompt, TaskModel.owner, TaskModel.id, TaskModel.context_notes, TaskModel.depends_on_task_id),
        "session_steps": (
            SessionStepModel.candidate,
            SessionStepModel.session_id,
            SessionStepModel.task_id,
            SessionStepModel.id,
        ),
        "user_skill_beliefs": (SkillBeliefModel.candidate,),
    }[name]


def _orm_to_list_dict(name: str, m) -> dict[str, Any]:
    if name == "tasks":
        from coach.tasks import task_to_dict

        d = task_to_dict(m)
        # task_to_dict nests parts; expose the raw JSON + flat scalars for the grid.
        d["parts_json"] = _preview(m.parts_json or "[]")
        d["tags_json"] = _preview(m.tags_json or "{}")
        d["created_at"] = m.created_at.isoformat() if m.created_at else None
        for k in ("prompt", "scaffold", "context_notes", "target_text"):
            if isinstance(d.get(k), str):
                d[k] = _preview(d[k])
        return d
    if name == "session_steps":
        return {
            "id": m.id,
            "session_id": m.session_id,
            "candidate": m.candidate,
            "step_index": m.step_index,
            "task_id": m.task_id,
            "role": m.role,
            "reward": m.reward,
            "inherited": bool(m.inherited),
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
    return {
        "id": m.id,
        "candidate": m.candidate,
        "level": m.level,
        "key": m.key,
        "mean": m.mean,
        "variance": m.variance,
        "questions_answered": m.questions_answered,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _orm_to_full_dict(name: str, m) -> dict[str, Any]:
    d = _orm_to_list_dict(name, m)
    if name == "tasks":
        d["prompt"] = m.prompt
        d["scaffold"] = m.scaffold
        d["context_notes"] = m.context_notes or ""
        d["parts_json"] = m.parts_json or "[]"
        d["tags_json"] = m.tags_json or "{}"
        d["target_text"] = m.target_text
    if name == "session_steps":
        d["task_snapshot_json"] = _preview(m.task_snapshot_json or "{}")
        d["state_before_json"] = _preview(m.state_before_json or "{}")
        d["state_after_json"] = _preview(m.state_after_json or "{}")
        d["result_json"] = _preview(m.result_json or "{}")
        d["coaching_json"] = _preview(m.coaching_json or "{}")
    return d


def _apply_orm_search(stmt, name: str, q: Optional[str]):
    if not (q or "").strip():
        return stmt
    from sqlalchemy import or_ as _or

    like = f"%{q.strip()}%"
    return stmt.where(_or(*[col.like(like) for col in _orm_search_cols(name)]))


def _apply_orm_filters(stmt, model, filters: dict):
    for k, v in filters.items():
        col = getattr(model, k, None)
        if col is not None:
            stmt = stmt.where(col == v)
    return stmt


def _apply_orm_sort(stmt, model, sort: str, order: str):
    col = getattr(model, sort, None)
    if col is None:
        return stmt
    return stmt.order_by(col.asc() if order == "asc" else col.desc())


def _count_orm_rows(name: str, q: Optional[str], filters: Optional[dict]) -> int:
    from sqlalchemy import func, select

    from coach.db import create_schema, learner_session

    create_schema()
    model = _orm_model(name)
    session = learner_session()
    try:
        stmt = select(func.count(model.id))
        stmt = _apply_orm_search(stmt, name, q)
        stmt = _apply_orm_filters(stmt, model, filters or {})
        return session.scalar(stmt) or 0
    finally:
        session.close()


def _list_orm_rows(name, page, page_size, q, sort, order, filters):
    from sqlalchemy import select

    from coach.db import create_schema, learner_session

    create_schema()
    model = _orm_model(name)
    session = learner_session()
    try:
        stmt = select(model)
        stmt = _apply_orm_search(stmt, name, q)
        stmt = _apply_orm_filters(stmt, model, filters)
        total_stmt = stmt
        from sqlalchemy import func

        total = session.scalar(select(func.count()).select_from(total_stmt.subquery())) or 0
        stmt = _apply_orm_sort(stmt, model, sort, order)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = session.scalars(stmt).all()
        return [_orm_to_list_dict(name, m) for m in rows], total
    finally:
        session.close()


def _get_orm_row(name: str, row_id: str) -> Optional[dict[str, Any]]:
    from coach.db import create_schema, learner_session

    create_schema()
    session = learner_session()
    try:
        m = session.get(_orm_model(name), row_id)
        return _orm_to_full_dict(name, m) if m else None
    finally:
        session.close()


def _delete_orm_row(name: str, row_id: str) -> int:
    from coach.db import create_schema, learner_session

    create_schema()
    session = learner_session()
    try:
        m = session.get(_orm_model(name), row_id)
        if m is None:
            return 0
        session.delete(m)
        session.commit()
        return 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _check_range(label: str, value: float, lo: float, hi: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.")
    if not (lo <= num <= hi):
        raise ValueError(f"{label} must be between {lo} and {hi}.")
    return num


def _update_task(task_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    from coach.db import create_schema, learner_session
    from coach.tasks import TaskModel

    create_schema()
    session = learner_session()
    try:
        m = session.get(TaskModel, task_id)
        if m is None:
            return None
        if "prompt" in fields:
            prompt = str(fields["prompt"] or "").strip()
            if not prompt:
                raise ValueError("prompt must not be empty.")
            m.prompt = prompt
        if "scaffold" in fields:
            m.scaffold = str(fields["scaffold"] or "") or None
        if "difficulty" in fields:
            try:
                diff = int(fields["difficulty"])
            except (TypeError, ValueError):
                raise ValueError("difficulty must be an integer 1..5.")
            if diff < 1 or diff > 5:
                raise ValueError("difficulty must be an integer 1..5.")
            m.difficulty = diff
        if "max_score" in fields:
            try:
                ms = int(fields["max_score"])
            except (TypeError, ValueError):
                raise ValueError("max_score must be an integer 1..100.")
            if ms < 1 or ms > 100:
                raise ValueError("max_score must be an integer 1..100.")
            m.max_score = ms
        if "parts_json" in fields:
            from coach.tasks import validate_parts

            raw = fields["parts_json"]
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raise ValueError("parts_json must be valid JSON (a list of parts).")
            m.parts_json = json.dumps(validate_parts(raw))
        if "context_notes" in fields:
            m.context_notes = str(fields["context_notes"] or "").strip()[:2000]
        if "tags_json" in fields:
            from coach.taxonomy import validate as validate_tags

            raw = fields["tags_json"]
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raise ValueError("tags_json must be valid JSON.")
            try:
                m.tags_json = json.dumps(validate_tags(raw))
            except ValueError as e:
                raise ValueError(str(e))
        if "task_type" in fields:
            from coach.taxonomy import TASK_TYPES

            if fields["task_type"] not in TASK_TYPES:
                raise ValueError(f"task_type must be one of {TASK_TYPES}.")
            m.task_type = fields["task_type"]
        if "version_index" in fields:
            try:
                vi = int(fields["version_index"])
            except (TypeError, ValueError):
                raise ValueError("version_index must be an integer >= 1.")
            if vi < 1:
                raise ValueError("version_index must be an integer >= 1.")
            m.version_index = vi
        if "depends_on_task_id" in fields:
            m.depends_on_task_id = str(fields["depends_on_task_id"] or "").strip() or None
        if "version_root_id" in fields:
            m.version_root_id = str(fields["version_root_id"] or "").strip() or None
        if "is_public" in fields:
            v = fields["is_public"]
            m.is_public = 1 if v in (True, 1, "1", "true", "True") else 0
        session.commit()
        return _orm_to_full_dict("tasks", m)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _update_step(step_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    from coach.db import create_schema, learner_session
    from coach.steps import SessionStepModel

    create_schema()
    session = learner_session()
    try:
        m = session.get(SessionStepModel, step_id)
        if m is None:
            return None
        if "reward" in fields:
            m.reward = _check_range("reward", fields["reward"], 0.0, 1.0)
        session.commit()
        return _orm_to_full_dict("session_steps", m)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _update_belief(belief_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    from datetime import datetime, timezone

    from coach.db import create_schema, learner_session
    from coach.tasks import SkillBeliefModel

    create_schema()
    session = learner_session()
    try:
        m = session.get(SkillBeliefModel, belief_id)
        if m is None:
            return None
        if "mean" in fields:
            m.mean = _check_range("mean", fields["mean"], 0.0, 1.0)
        if "variance" in fields:
            m.variance = _check_range("variance", fields["variance"], 0.0001, 1.0)
        if "questions_answered" in fields:
            try:
                qa = int(fields["questions_answered"])
            except (TypeError, ValueError):
                raise ValueError("questions_answered must be an integer >= 0.")
            if qa < 0:
                raise ValueError("questions_answered must be an integer >= 0.")
            m.questions_answered = qa
        m.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
        return _orm_to_full_dict("user_skill_beliefs", m)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _update_user(user_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    from coach.db import create_schema, sqlite_conn

    create_schema()
    name = str(fields.get("display_name") or "").strip()
    if len(name) > 255:
        raise ValueError("display_name must be at most 255 characters.")
    with sqlite_conn() as conn:
        cur = conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, user_id))
        conn.commit()
        if cur.rowcount == 0:
            return None
    return _get_raw_row("users", user_id)


# --- raw-sqlite tables (users / auth_tokens / active_sessions) ---

_RAW_SELECT = {
    "users": "SELECT id, email, display_name, created_at FROM users",
    "auth_tokens": "SELECT token, user_id, created_at, expires_at FROM auth_tokens",
    "active_sessions": "SELECT session_id, candidate, status, session_json, resumed_from_share, fork_of, updated_at FROM active_sessions",
}

_RAW_COLS = {
    "users": ("id", "email", "display_name", "created_at"),
    "auth_tokens": ("token", "user_id", "created_at", "expires_at"),
    "active_sessions": ("session_id", "candidate", "status", "session_json", "resumed_from_share", "fork_of", "updated_at"),
}

_RAW_PK = {"users": "id", "auth_tokens": "token", "active_sessions": "session_id"}


def _raw_searchable(name: str) -> tuple:
    return tuple(c["name"] for c in TABLE_REGISTRY[name]["columns"] if c.get("searchable"))


def _raw_where(name: str, q: Optional[str], filters: dict) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if (q or "").strip() and _raw_searchable(name):
        like = f"%{q.strip()}%"
        clauses.append("(" + " OR ".join(f"{c} LIKE ?" for c in _raw_searchable(name)) + ")")
        params.extend([like] * len(_raw_searchable(name)))
    for k, v in filters.items():
        clauses.append(f"{k} = ?")
        params.append(v)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _count_raw_rows(name: str, q: Optional[str], filters: Optional[dict]) -> int:
    from coach.db import create_schema, sqlite_conn

    create_schema()
    where, params = _raw_where(name, q, filters or {})
    with sqlite_conn() as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {name}{where}", params).fetchone()
        return row[0] if row else 0


def _list_raw_rows(name, page, page_size, q, sort, order, filters):
    from coach.db import create_schema, sqlite_conn

    create_schema()
    where, params = _raw_where(name, q, filters)
    direction = "ASC" if order == "asc" else "DESC"
    cols = _RAW_COLS[name]
    with sqlite_conn() as conn:
        total_row = conn.execute(f"SELECT COUNT(*) FROM {name}{where}", params).fetchone()
        total = total_row[0] if total_row else 0
        rows = conn.execute(
            f"{_RAW_SELECT[name]}{where} ORDER BY {sort} {direction} LIMIT ? OFFSET ?",
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if isinstance(d.get("session_json"), str):
            d["session_json"] = _preview(d["session_json"])
        out.append(d)
    return out, total


def _get_raw_row(name: str, row_id: str) -> Optional[dict[str, Any]]:
    from coach.db import create_schema, sqlite_conn

    create_schema()
    pk = _RAW_PK[name]
    with sqlite_conn() as conn:
        row = conn.execute(f"{_RAW_SELECT[name]} WHERE {pk} = ?", (row_id,)).fetchone()
    if row is None:
        return None
    return dict(zip(_RAW_COLS[name], row))


def _delete_raw_row(name: str, row_id: str) -> dict[str, Any]:
    from coach.db import create_schema, sqlite_conn

    create_schema()
    pk = _RAW_PK[name]
    with sqlite_conn() as conn:
        if name == "users":
            tok = conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (row_id,))
            usr = conn.execute("DELETE FROM users WHERE id = ?", (row_id,))
            conn.commit()
            return {"deleted": usr.rowcount or 0, "deleted_tokens": tok.rowcount or 0}
        if name == "active_sessions":
            from coach.steps import delete_session_data

            delete_session_data(row_id)
        cur = conn.execute(f"DELETE FROM {name} WHERE {pk} = ?", (row_id,))
        conn.commit()
        return {"deleted": cur.rowcount or 0}
