"""RL-shaped per-step session storage (``session_steps``).

One row per scored answer in a session — the episode's transition
``(s_t, a_t, r_t, s_{t+1})`` plus immutable observation (task snapshot) and
coaching. Supersedes the legacy ``task_attempts`` table and the
``feedback_json`` blob. This is the single source of truth for step data:
resume/review read from here, shares snapshot from here, and a future episode
export is a plain SELECT.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from coach.db import Base, learner_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SessionStepModel(Base):
    __tablename__ = "session_steps"
    __table_args__ = (
        Index("uq_session_steps", "session_id", "step_index", unique=True),
        Index("ix_session_steps_task", "task_id"),
        Index("ix_session_steps_candidate", "candidate"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate: Mapped[str] = mapped_column(String(255), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    task_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="bank")
    user_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    fraction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reward: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hints_used_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    state_before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    state_after_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    coaching_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    inherited: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def _safe_json(raw: str, default):
    try:
        parsed = json.loads(raw or "")
    except Exception:
        return default
    return parsed if parsed is not None else default


def step_to_dict(m: SessionStepModel) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "candidate": m.candidate,
        "step_index": m.step_index,
        "task_id": m.task_id,
        "task_snapshot": _safe_json(m.task_snapshot_json, {}),
        "role": m.role,
        "user_answer": m.user_answer or "",
        "score": m.score,
        "max_score": m.max_score,
        "fraction": m.fraction,
        "reward": m.reward,
        "hints_used": _safe_json(m.hints_used_json, []),
        "state_before": _safe_json(m.state_before_json, {}),
        "state_after": _safe_json(m.state_after_json, {}),
        "result": _safe_json(m.result_json, {}),
        "coaching": _safe_json(m.coaching_json, {}),
        "inherited": bool(m.inherited),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def insert_step(
    session_id: str,
    candidate: str,
    step_index: int,
    task: dict | None,
    role: str,
    user_answer: str,
    score: float,
    max_score: float,
    fraction: float,
    reward: float,
    hints_used: Optional[list],
    state_before: dict | None,
    state_after: dict | None,
    result: dict | None,
    coaching: dict | None,
    inherited: bool = False,
) -> str:
    """Append one RL-transition row to a session."""
    from coach.db import create_schema

    create_schema()
    sid = str(uuid.uuid4())
    session = learner_session()
    try:
        session.add(
            SessionStepModel(
                id=sid,
                session_id=session_id,
                candidate=candidate,
                step_index=step_index,
                task_id=(task or {}).get("id"),
                task_snapshot_json=json.dumps(task or {}),
                role=role or "bank",
                user_answer=user_answer or "",
                score=float(score or 0.0),
                max_score=float(max_score or 5.0),
                fraction=max(0.0, min(1.0, float(fraction or 0.0))),
                reward=float(reward or 0.0),
                hints_used_json=json.dumps(hints_used or []),
                state_before_json=json.dumps(state_before or {}),
                state_after_json=json.dumps(state_after or {}),
                result_json=json.dumps(result or {}),
                coaching_json=json.dumps(coaching or {}),
                inherited=1 if inherited else 0,
                created_at=_utcnow_naive(),
            )
        )
        session.commit()
        return sid
    finally:
        session.close()


def answer_for_task(session_id: str, task_id: str) -> Optional[str]:
    """The user's submitted code for a task in a session (latest step), or None."""
    from coach.db import create_schema, learner_session

    create_schema()
    session = learner_session()
    try:
        m = session.scalars(
            select(SessionStepModel)
            .where(
                SessionStepModel.session_id == session_id,
                SessionStepModel.task_id == task_id,
            )
            .order_by(SessionStepModel.step_index.desc())
            .limit(1)
        ).first()
        return (m.user_answer or "") if m else None
    finally:
        session.close()


def list_steps(session_id: str) -> list[dict]:
    """Steps of a session, ordered by ``step_index`` (dict forms)."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        rows = session.scalars(
            select(SessionStepModel)
            .where(SessionStepModel.session_id == session_id)
            .order_by(SessionStepModel.step_index)
        ).all()
        return [step_to_dict(m) for m in rows]
    finally:
        session.close()


def count_steps(session_id: str) -> int:
    from coach.db import create_schema
    from sqlalchemy import func

    create_schema()
    session = learner_session()
    try:
        return session.scalar(
            select(func.count(SessionStepModel.id)).where(
                SessionStepModel.session_id == session_id
            )
        ) or 0
    finally:
        session.close()


def delete_steps_for_task(task_id: str) -> int:
    """Delete all steps referencing a task (cascade on task delete)."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        n = (
            session.query(SessionStepModel)
            .filter(SessionStepModel.task_id == task_id)
            .delete(synchronize_session=False)
        )
        session.commit()
        return n or 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def delete_session_data(session_id: str) -> None:
    """Delete a session's steps and any shares pointing at it."""
    from coach.db import create_schema, sqlite_conn

    create_schema()
    try:
        from coach.shares import delete_shares_for_source

        delete_shares_for_source(session_id)
    except Exception:
        pass
    session = learner_session()
    try:
        session.query(SessionStepModel).filter(
            SessionStepModel.session_id == session_id
        ).delete(synchronize_session=False)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def belief_state(session) -> dict:
    """Serialized belief snapshot: global + family + tag sufficient stats.

    This is the RL ``s_t`` — what gets stored per step and carried through
    shares. ``session.ensure_area_beliefs()`` must be called first so the
    per-level stats reflect the candidate's persisted beliefs.
    """
    ability = session.get_ability()
    return {
        "global": ability.to_dict(),
        "families": {k: v.to_dict() for k, v in session.family_states.items()},
        "tags": {k: v.to_dict() for k, v in session.tag_states.items()},
    }


def backfill_session_steps() -> None:
    """Reconstruct ``session_steps`` from legacy JSON blobs (best-effort).

    For every ``active_sessions`` row whose stored ``session_json`` still
    carries a non-empty legacy ``results`` list and has no steps yet, replay
    the belief updates in order (deterministic) and write one step row per
    result. Idempotent: sessions that already have steps are skipped, and
    failures are swallowed so startup never breaks.
    """
    from coach.area_score import AreaState
    from coach.db import create_schema, learner_session, sqlite_conn
    from coach.score import (
        INITIAL_SCORE,
        INITIAL_VARIANCE,
        bayesian_update,
        effective_score,
        measurement_variance,
    )
    from coach.session import SkillState
    from coach.taxonomy import family_of

    # Ensure tables exist (no-op inside create_schema thanks to the guard).
    create_schema()

    rows: list[tuple] = []
    try:
        with sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT session_id, candidate, session_json, feedback_json FROM active_sessions"
            ).fetchall()
    except Exception:
        return

    session = learner_session()
    try:
        existing = {
            sid
            for (sid,) in session.execute(
                select(SessionStepModel.session_id).distinct()
            ).all()
        }
    except Exception:
        return
    finally:
        session.close()

    for sid, candidate, session_json, feedback_json in rows:
        if sid in existing:
            continue
        try:
            s = json.loads(session_json or "{}")
            results = s.get("results") if isinstance(s, dict) else None
            if not results:
                continue
            try:
                feedback = json.loads(feedback_json or "[]")
            except Exception:
                feedback = []
            _backfill_one(sid, candidate or "", s, results, feedback)
        except Exception:
            continue


def _backfill_one(sid: str, candidate: str, s: dict, results: list, feedback: list) -> None:
    from coach.area_score import AreaState
    from coach.score import (
        INITIAL_SCORE,
        INITIAL_VARIANCE,
        bayesian_update,
        effective_score,
        measurement_variance,
    )
    from coach.session import SkillState
    from coach.taxonomy import family_of

    tasks = s.get("tasks") or []
    by_id = {t.get("id"): t for t in tasks}
    ability = SkillState()
    fam_states: dict[str, AreaState] = {}
    tag_states: dict[str, AreaState] = {}

    for i, res in enumerate(results):
        task = by_id.get((res or {}).get("task_id")) or (
            tasks[i] if i < len(tasks) else {}
        )
        fb = feedback[i] if i < len(feedback) else {}
        hints_used = fb.get("hints_used") or []
        max_score = max(1.0, float((res or {}).get("max_score") or 5.0))
        raw_fraction = max(0.0, min(1.0, float((res or {}).get("score") or 0.0) / max_score))
        observation = effective_score(raw_fraction)

        before = {
            "global": ability.to_dict(),
            "families": {k: v.to_dict() for k, v in fam_states.items()},
            "tags": {k: v.to_dict() for k, v in tag_states.items()},
        }

        difficulty = task.get("difficulty", 1)
        obs_var = measurement_variance(difficulty, ability.score)
        new_mean, new_var = bayesian_update(
            ability.score, ability.variance, observation, obs_var
        )
        ability = SkillState(
            score=new_mean,
            variance=new_var,
            questions_answered=ability.questions_answered + 1,
            evidence=list(ability.evidence) + [(res or {}).get("rationale", "")],
        )
        tags = task.get("tags") or {}
        primary = tags.get("primary")
        fam = family_of(primary) if primary else None
        if primary:
            st = tag_states.get(primary, AreaState())
            tag_states[primary] = st.update(difficulty, observation)
        if fam:
            st = fam_states.get(fam, AreaState())
            fam_states[fam] = st.update(difficulty, observation)

        after = {
            "global": ability.to_dict(),
            "families": {k: v.to_dict() for k, v in fam_states.items()},
            "tags": {k: v.to_dict() for k, v in tag_states.items()},
        }

        role = "bank"
        if task.get("generated"):
            role = str(task.get("generated_kind") or "remediate")
        insert_step(
            sid,
            candidate,
            i,
            task,
            role,
            fb.get("user_answer") or "",
            float((res or {}).get("score") or 0.0),
            max_score,
            raw_fraction,
            observation,
            hints_used,
            before,
            after,
            res or {},
            (res or {}).get("coach") or fb.get("coach") or {},
            inherited=False,
        )