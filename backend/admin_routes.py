"""Admin/debug API routes for inspecting the knowledge graph and learner model."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from backend.auth import get_current_user, is_admin
from backend.dependencies import get_store
from learner.engine import LearnerEngine

admin_router = APIRouter(prefix="/admin", tags=["admin"])


def _require_user(user: dict = Depends(get_current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _require_owner_or_admin(candidate: str, user: dict) -> dict:
    """Owner-only + admin: the candidate themselves or an ADMIN_EMAILS admin."""
    email = (user.get("email") or "").strip().lower()
    if email == (candidate or "").strip().lower() or is_admin(user):
        return user
    raise HTTPException(status_code=403, detail="Not authorized for this candidate.")


def _require_admin(user: dict = Depends(_require_user)) -> dict:
    """Admin-only: the knowledge graph is global, so only ADMIN_EMAILS may wipe it."""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


@admin_router.get("/learners")
def list_learners(user: dict = Depends(_require_user)):
    """List all learners (candidate → learner_id on the learners row)."""
    from sqlalchemy import select

    from learner.states import LearnerModel

    engine = LearnerEngine()
    session = engine._session()
    try:
        rows = session.scalars(
            select(LearnerModel).order_by(LearnerModel.created_at.desc())
        ).all()
    finally:
        session.close()

    learners = []
    for m in rows:
        meta = dict(m.meta or {})
        learners.append({
            "candidate": m.candidate,
            "learner_id": m.id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "metadata": meta,
        })

    return {"learners": learners}


@admin_router.get("/graph")
def get_graph(user: dict = Depends(_require_user)):
    """Return all knowledge graph nodes and edges."""
    engine = LearnerEngine()
    session = engine._session()
    try:
        container = engine._container(session)
        nodes_raw = container.knowledge_repository.list_all_nodes() if hasattr(container.knowledge_repository, 'list_all_nodes') else []
        if not nodes_raw:
            from learner.graph import KnowledgeNodeModel, KnowledgeEdgeModel
            from sqlalchemy import select
            node_models = session.scalars(select(KnowledgeNodeModel)).all()
            edge_models = session.scalars(select(KnowledgeEdgeModel)).all()

            nodes = []
            node_id_set = set()
            for m in node_models:
                node_id_set.add(m.id)
                nodes.append({
                    "id": m.id,
                    "type": m.type,
                    "slug": m.slug,
                    "name": m.name,
                    "description": m.description,
                    "importance": (m.meta or {}).get("importance", 0.7),
                    "status": m.status,
                })

            edges = []
            for m in edge_models:
                edges.append({
                    "id": m.id,
                    "source": m.source_node_id,
                    "target": m.target_node_id,
                    "edge_type": m.edge_type,
                    "weight": m.weight,
                })
        else:
            nodes = [
                {
                    "id": str(n.id),
                    "type": n.type.value if hasattr(n.type, 'value') else str(n.type),
                    "slug": n.slug,
                    "name": n.name,
                    "description": n.description,
                    "importance": n.metadata.get("importance", 0.7),
                    "status": n.status.value if hasattr(n.status, 'value') else str(n.status),
                }
                for n in nodes_raw
            ]
            edges_raw = []
            for n in nodes_raw:
                edges_raw.extend(container.knowledge_repository.get_outgoing_edges(n.id))
            seen = set()
            edges = []
            for e in edges_raw:
                key = (str(e.source_node_id), str(e.target_node_id), str(e.edge_type))
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "id": str(e.id),
                        "source": str(e.source_node_id),
                        "target": str(e.target_node_id),
                        "edge_type": e.edge_type.value if hasattr(e.edge_type, 'value') else str(e.edge_type),
                        "weight": e.weight,
                    })

        return {"nodes": nodes, "edges": edges}
    finally:
        session.close()


@admin_router.get("/graph/summary")
def graph_summary_endpoint(user: dict = Depends(_require_user)):
    """Dry-run preview: global graph row counts + dependent learner rows."""
    from coach.admin import graph_summary

    return graph_summary()


@admin_router.delete("/graph")
def delete_graph_endpoint(user: dict = Depends(_require_admin)):
    """Full reset: delete global graph nodes/edges + dependent learner rows."""
    from coach.admin import clear_knowledge_graph

    return {"ok": True, **clear_knowledge_graph()}


@admin_router.get("/graph/{node_id}")
def get_node_detail(node_id: str, user: dict = Depends(_require_user)):
    """Return a single node with its connections."""
    import uuid as _uuid
    engine = LearnerEngine()
    session = engine._session()
    try:
        container = engine._container(session)
        nid = _uuid.UUID(node_id)
        node = container.knowledge_repository.get_node(nid)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found.")

        outgoing = container.knowledge_repository.get_outgoing_edges(nid)
        incoming = container.knowledge_repository.get_incoming_edges(nid)
        related = container.knowledge_repository.get_related_nodes(nid)

        return {
            "node": {
                "id": str(node.id),
                "type": node.type.value if hasattr(node.type, 'value') else str(node.type),
                "slug": node.slug,
                "name": node.name,
                "description": node.description,
                "importance": node.metadata.get("importance", 0.7),
                "status": node.status.value if hasattr(node.status, 'value') else str(node.status),
            },
            "outgoing_edges": [
                {
                    "id": str(e.id),
                    "target": str(e.target_node_id),
                    "edge_type": e.edge_type.value if hasattr(e.edge_type, 'value') else str(e.edge_type),
                    "weight": e.weight,
                }
                for e in outgoing
            ],
            "incoming_edges": [
                {
                    "id": str(e.id),
                    "source": str(e.source_node_id),
                    "edge_type": e.edge_type.value if hasattr(e.edge_type, 'value') else str(e.edge_type),
                    "weight": e.weight,
                }
                for e in incoming
            ],
            "related_nodes": [
                {
                    "id": str(n.id),
                    "type": n.type.value if hasattr(n.type, 'value') else str(n.type),
                    "slug": n.slug,
                    "name": n.name,
                }
                for n in related
            ],
        }
    finally:
        session.close()


@admin_router.get("/learner/{candidate}")
def get_learner_detail(candidate: str, user: dict = Depends(_require_user)):
    """Return full learner model data for a candidate."""
    engine = LearnerEngine()
    learner_id = engine.learner_id(candidate)
    if learner_id is None:
        raise HTTPException(status_code=404, detail="No learner found for this candidate.")

    session = engine._session()
    try:
        container = engine._container(session)
        import uuid as _uuid

        # Knowledge states
        states = []
        for s in container.learner_service.list_learner_states(learner_id):
            node = container.knowledge_repository.get_node(s.node_id)
            states.append({
                "node_id": str(s.node_id),
                "slug": node.slug if node else str(s.node_id),
                "node_name": node.name if node else str(s.node_id),
                "node_type": (node.type.value if hasattr(node.type, 'value') else str(node.type)) if node else "unknown",
                "mastery": s.mastery,
                "uncertainty": s.uncertainty,
                "status": s.status.value if hasattr(s.status, 'value') else str(s.status),
                "evidence_count": s.evidence_count,
                "conceptual": s.conceptual,
                "procedural": s.procedural,
                "implementation": s.implementation,
                "transfer": s.transfer,
                "fluency": s.fluency,
                "self_confidence": s.self_confidence,
                "reasoning": s.reasoning,
            })

        # Frontier
        frontier = []
        for f in container.frontier_service.list_frontier(learner_id):
            node = container.knowledge_repository.get_node(f.node_id)
            frontier.append({
                "node_id": str(f.node_id),
                "slug": node.slug if node else str(f.node_id),
                "node_name": node.name if node else str(f.node_id),
                "priority": f.priority,
                "reason": f.reason,
                "status": f.status.value if hasattr(f.status, 'value') else str(f.status),
            })

        # Misconceptions
        misconceptions = []
        for mc in container.misconception_service.list_all(learner_id):
            if not mc.is_active:
                continue
            node = container.knowledge_repository.get_node(mc.misconception_node_id)
            misconceptions.append({
                "id": str(mc.id),
                "node_id": str(mc.misconception_node_id),
                "slug": node.slug if node else str(mc.misconception_node_id),
                "node_name": node.name if node else "",
                "description": node.description if node else "",
                "confidence": mc.confidence,
                "status": mc.status.value if hasattr(mc.status, 'value') else str(mc.status),
                "first_detected_at": mc.first_detected_at.isoformat() if mc.first_detected_at else None,
                "last_observed_at": mc.last_observed_at.isoformat() if mc.last_observed_at else None,
            })

        # Evidence
        evidence = []
        for ev in container.evidence_repository.list_evidence_for_learner(learner_id):
            node = container.knowledge_repository.get_node(ev.node_id)
            evidence.append({
                "id": str(ev.id),
                "node_id": str(ev.node_id),
                "slug": node.slug if node else str(ev.node_id),
                "evidence_type": ev.evidence_type.value if hasattr(ev.evidence_type, 'value') else str(ev.evidence_type),
                "observation_status": ev.observation_status.value if hasattr(ev.observation_status, 'value') else str(ev.observation_status),
                "correctness": ev.correctness,
                "assessor_explanation": ev.assessor_explanation,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            })

        # Next action
        frontier_entries = container.frontier_service.list_frontier(learner_id)
        actions = container.policy_engine.generate(learner_id, frontier_entries)
        next_action = None
        if actions:
            a = actions[0]
            node = container.knowledge_repository.get_node(a.target_node_id)
            next_action = {
                "action_type": a.action_type.value if hasattr(a.action_type, 'value') else str(a.action_type),
                "target_node_id": str(a.target_node_id),
                "slug": node.slug if node else str(a.target_node_id),
                "total_score": a.total_score,
                "rationale": a.rationale,
            }

        return {
            "learner_id": str(learner_id),
            "candidate": candidate,
            "states": states,
            "frontier": frontier,
            "misconceptions": misconceptions,
            "evidence": evidence,
            "next_action": next_action,
        }
    finally:
        session.close()


@admin_router.get("/skill-states/{candidate}")
def get_skill_states(candidate: str, user: dict = Depends(_require_user)):
    """Return parent app Bayesian SkillState for a candidate's active sessions."""
    from coach.session import Session

    store = get_store()
    active = store.list_by_candidate(candidate)
    if active:
        state = store.get(active[0]["session_id"])
        if state and "session" in state:
            session = Session.from_dict(state["session"])
            return {
                "source": "active_session",
                "session_id": active[0]["session_id"],
                "skill_states": {
                    k: {
                        "score": v.score,
                        "variance": v.variance,
                        "confidence": v.confidence,
                        "questions_answered": v.questions_answered,
                    }
                    for k, v in session.skill_states.items()
                },
            }

    return {"source": "none", "skill_states": {}}


@admin_router.get("/stats")
def get_stats(user: dict = Depends(_require_user)):
    """Return summary counts across both databases."""
    engine = LearnerEngine()
    session = engine._session()
    try:
        from learner.graph import KnowledgeNodeModel, KnowledgeEdgeModel
        from learner.evidence import EvidenceModel
        from learner.states import LearnerModel, LearnerKnowledgeStateModel
        from learner.misconception import LearnerMisconceptionModel
        from sqlalchemy import func, select

        node_count = session.scalar(select(func.count(KnowledgeNodeModel.id))) or 0
        edge_count = session.scalar(select(func.count(KnowledgeEdgeModel.id))) or 0
        learner_count = session.scalar(select(func.count(LearnerModel.id))) or 0
        state_count = session.scalar(select(func.count(LearnerKnowledgeStateModel.id))) or 0
        evidence_count = session.scalar(select(func.count(EvidenceModel.id))) or 0
        misconception_count = session.scalar(select(func.count(LearnerMisconceptionModel.id))) or 0

        return {
            "knowledge_nodes": node_count,
            "knowledge_edges": edge_count,
            "learners": learner_count,
            "knowledge_states": state_count,
            "evidence_records": evidence_count,
            "misconceptions": misconception_count,
        }
    finally:
        session.close()


@admin_router.get("/tasks")
def list_tasks_admin(
    owner: Optional[str] = None,
    skill: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(_require_user),
):
    """List task-bank rows with attempt counts (for the Manage tab)."""
    from coach.tasks import list_tasks_for_admin

    tasks = list_tasks_for_admin(owner=owner, skill=skill, q=q, limit=limit)
    return {"tasks": tasks}


@admin_router.get("/candidate/{candidate}/summary")
def candidate_summary_endpoint(candidate: str, user: dict = Depends(_require_user)):
    """Dry-run preview: per-table row counts for a candidate (owner or admin)."""
    from coach.admin import candidate_summary

    _require_owner_or_admin(candidate, user)
    return candidate_summary(candidate)


@admin_router.delete("/candidate/{candidate}")
def delete_candidate_endpoint(candidate: str, user: dict = Depends(_require_user)):
    """Full candidate wipe: sessions + learner rows + attempts + beliefs + owned tasks."""
    from coach.admin import clear_candidate_everything

    _require_owner_or_admin(candidate, user)
    return {"ok": True, **clear_candidate_everything(candidate)}


@admin_router.delete("/tasks/{task_id}")
def delete_task_endpoint(task_id: str, user: dict = Depends(_require_user)):
    """Delete one question plus its attempts (cascade).

    Allowed for the task owner or an ADMIN_EMAILS admin (system seed rows
    are admin-only).
    """
    from coach.tasks import delete_task, get_task

    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    email = (user.get("email") or "").strip().lower()
    if (task.get("owner") or "") != email and not is_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized to delete this task.")
    result = delete_task(task_id)
    return {"ok": True, "task_id": task_id, **result}
