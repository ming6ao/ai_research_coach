"""Admin management helpers: per-candidate summaries and full wipes.

Candidate-scoped rows live in several places:

- ``active_sessions`` (raw sqlite, ``candidate`` column)
- ``learners`` + ``learner_knowledge_states`` / ``evidence`` /
  ``learner_misconceptions`` / ``learner_frontier`` (ORM, via ``learner_id``)
- ``task_attempts`` (ORM, ``candidate`` column)
- ``user_skill_beliefs`` (ORM, ``candidate`` column)
- ``tasks`` (ORM, ``owner`` column)

Knowledge graph nodes/edges, ``users`` and ``auth_tokens`` are global and
are never touched here — except by the explicit graph helpers below
(``graph_summary`` / ``clear_knowledge_graph``), which exist for the
admin-only full reset on the debug Manage page.
"""

from __future__ import annotations

from sqlalchemy import func, select

from coach.db import create_schema, learner_session, sqlite_conn


def candidate_summary(candidate: str) -> dict:
    """Count candidate-scoped rows per table (dry-run preview for wipes)."""
    create_schema()
    with sqlite_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM active_sessions WHERE candidate = ?",
            (candidate,),
        ).fetchone()
        sessions = row[0] if row else 0

    session = learner_session()
    try:
        from learner.evidence import EvidenceModel
        from learner.frontier import LearnerFrontierModel
        from learner.misconception import LearnerMisconceptionModel
        from learner.states import LearnerKnowledgeStateModel, LearnerModel

        from coach.tasks import SkillBeliefModel, TaskAttemptModel, TaskModel

        learner = session.scalar(
            select(LearnerModel).where(LearnerModel.candidate == candidate)
        )
        if learner is None:
            learner_rows = states = evidence = frontier = misconceptions = 0
        else:
            lid = learner.id
            learner_rows = 1
            states = (
                session.scalar(
                    select(func.count(LearnerKnowledgeStateModel.id)).where(
                        LearnerKnowledgeStateModel.learner_id == lid
                    )
                )
                or 0
            )
            evidence = (
                session.scalar(
                    select(func.count(EvidenceModel.id)).where(
                        EvidenceModel.learner_id == lid
                    )
                )
                or 0
            )
            frontier = (
                session.scalar(
                    select(func.count(LearnerFrontierModel.id)).where(
                        LearnerFrontierModel.learner_id == lid
                    )
                )
                or 0
            )
            misconceptions = (
                session.scalar(
                    select(func.count(LearnerMisconceptionModel.id)).where(
                        LearnerMisconceptionModel.learner_id == lid
                    )
                )
                or 0
            )

        attempts = (
            session.scalar(
                select(func.count(TaskAttemptModel.id)).where(
                    TaskAttemptModel.candidate == candidate
                )
            )
            or 0
        )
        beliefs = (
            session.scalar(
                select(func.count(SkillBeliefModel.id)).where(
                    SkillBeliefModel.candidate == candidate
                )
            )
            or 0
        )
        owned_tasks = (
            session.scalar(
                select(func.count(TaskModel.id)).where(
                    TaskModel.owner == candidate
                )
            )
            or 0
        )
    finally:
        session.close()

    total = (
        sessions
        + learner_rows
        + states
        + evidence
        + frontier
        + misconceptions
        + attempts
        + beliefs
        + owned_tasks
    )
    return {
        "candidate": candidate,
        "active_sessions": sessions,
        "learners": learner_rows,
        "knowledge_states": states,
        "evidence": evidence,
        "frontier": frontier,
        "misconceptions": misconceptions,
        "task_attempts": attempts,
        "skill_beliefs": beliefs,
        "owned_tasks": owned_tasks,
        "total": total,
    }


def clear_candidate_everything(candidate: str) -> dict:
    """Delete all candidate-scoped rows; return per-table deleted counts."""
    create_schema()
    deleted: dict[str, int] = {
        "active_sessions": 0,
        "learners": 0,
        "knowledge_states": 0,
        "evidence": 0,
        "frontier": 0,
        "misconceptions": 0,
        "task_attempts": 0,
        "skill_beliefs": 0,
        "owned_tasks": 0,
    }

    with sqlite_conn() as conn:
        cur = conn.execute(
            "DELETE FROM active_sessions WHERE candidate = ?", (candidate,)
        )
        deleted["active_sessions"] = cur.rowcount or 0

    session = learner_session()
    try:
        from learner.evidence import EvidenceModel
        from learner.frontier import LearnerFrontierModel
        from learner.misconception import LearnerMisconceptionModel
        from learner.states import LearnerKnowledgeStateModel, LearnerModel

        from coach.tasks import SkillBeliefModel, TaskAttemptModel, TaskModel

        learner = session.scalar(
            select(LearnerModel).where(LearnerModel.candidate == candidate)
        )
        if learner is not None:
            lid = learner.id
            deleted["misconceptions"] = (
                session.query(LearnerMisconceptionModel)
                .filter(LearnerMisconceptionModel.learner_id == lid)
                .delete(synchronize_session=False)
            )
            deleted["frontier"] = (
                session.query(LearnerFrontierModel)
                .filter(LearnerFrontierModel.learner_id == lid)
                .delete(synchronize_session=False)
            )
            deleted["evidence"] = (
                session.query(EvidenceModel)
                .filter(EvidenceModel.learner_id == lid)
                .delete(synchronize_session=False)
            )
            deleted["knowledge_states"] = (
                session.query(LearnerKnowledgeStateModel)
                .filter(LearnerKnowledgeStateModel.learner_id == lid)
                .delete(synchronize_session=False)
            )
            deleted["learners"] = (
                session.query(LearnerModel)
                .filter(LearnerModel.id == lid)
                .delete(synchronize_session=False)
            )

        deleted["task_attempts"] = (
            session.query(TaskAttemptModel)
            .filter(TaskAttemptModel.candidate == candidate)
            .delete(synchronize_session=False)
        )
        deleted["skill_beliefs"] = (
            session.query(SkillBeliefModel)
            .filter(SkillBeliefModel.candidate == candidate)
            .delete(synchronize_session=False)
        )
        deleted["owned_tasks"] = (
            session.query(TaskModel)
            .filter(TaskModel.owner == candidate)
            .delete(synchronize_session=False)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    deleted["total"] = sum(deleted.values())
    return {"candidate": candidate, "deleted": deleted}


def graph_summary() -> dict:
    """Count global knowledge-graph rows plus dependent learner rows.

    Dependent rows (states/evidence/frontier/misconceptions) all FK to
    ``knowledge_nodes.id``, so a full reset must delete them together
    with the graph to avoid orphans.
    """
    create_schema()
    session = learner_session()
    try:
        from learner.evidence import EvidenceModel
        from learner.frontier import LearnerFrontierModel
        from learner.graph import KnowledgeEdgeModel, KnowledgeNodeModel
        from learner.misconception import LearnerMisconceptionModel
        from learner.states import LearnerKnowledgeStateModel

        nodes = session.scalar(select(func.count(KnowledgeNodeModel.id))) or 0
        edges = session.scalar(select(func.count(KnowledgeEdgeModel.id))) or 0
        states = session.scalar(select(func.count(LearnerKnowledgeStateModel.id))) or 0
        evidence = session.scalar(select(func.count(EvidenceModel.id))) or 0
        frontier = session.scalar(select(func.count(LearnerFrontierModel.id))) or 0
        misconceptions = (
            session.scalar(select(func.count(LearnerMisconceptionModel.id))) or 0
        )
    finally:
        session.close()

    total = nodes + edges + states + evidence + frontier + misconceptions
    return {
        "knowledge_nodes": nodes,
        "knowledge_edges": edges,
        "knowledge_states": states,
        "evidence": evidence,
        "frontier": frontier,
        "misconceptions": misconceptions,
        "total": total,
    }


def clear_knowledge_graph() -> dict:
    """Full reset: delete the global graph + all dependent learner rows.

    Delete order (dependents first, then edges, then nodes) avoids FK
    violations. Per-learner progress is gone afterwards; the graph
    rebuilds on the next ``bootstrap_task`` / ``record_submission``.
    Returns per-table deleted counts.
    """
    create_schema()
    deleted: dict[str, int] = {
        "misconceptions": 0,
        "frontier": 0,
        "evidence": 0,
        "knowledge_states": 0,
        "knowledge_edges": 0,
        "knowledge_nodes": 0,
    }

    session = learner_session()
    try:
        from learner.evidence import EvidenceModel
        from learner.frontier import LearnerFrontierModel
        from learner.graph import KnowledgeEdgeModel, KnowledgeNodeModel
        from learner.misconception import LearnerMisconceptionModel
        from learner.states import LearnerKnowledgeStateModel

        deleted["misconceptions"] = (
            session.query(LearnerMisconceptionModel).delete(
                synchronize_session=False
            )
        )
        deleted["frontier"] = (
            session.query(LearnerFrontierModel).delete(synchronize_session=False)
        )
        deleted["evidence"] = (
            session.query(EvidenceModel).delete(synchronize_session=False)
        )
        deleted["knowledge_states"] = (
            session.query(LearnerKnowledgeStateModel).delete(
                synchronize_session=False
            )
        )
        deleted["knowledge_edges"] = (
            session.query(KnowledgeEdgeModel).delete(synchronize_session=False)
        )
        deleted["knowledge_nodes"] = (
            session.query(KnowledgeNodeModel).delete(synchronize_session=False)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    deleted["total"] = sum(deleted.values())
    return {"deleted": deleted}
