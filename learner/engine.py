"""LearnerEngine: the single facade connecting the app to the learner model.

The parent app drives; the learner package stores. This module:

- owns the learner session factory + container (one short-lived session per call),
- persists the candidate -> learner_id identity on the ``learners`` row
  (``learners.candidate``, UNIQUE),
- bootstraps the knowledge graph from a picked task
  (via ``TaskDecomposer``),
- turns a judge result into immutable evidence and runs
  evidence -> state update -> misconception -> frontier -> policy,
- produces a learner snapshot for the progress view,
- centralizes next-task selection (``pick_next_task``): pending generated task,
  frontier remediation, then the EIG bank picker.

The learner model is LLM-free: all decomposition LLM calls live in
``coach.task_decomposer``.
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from coach.db import learner_db_url
from coach.task_decomposer import TaskDecomposer
from learner.container import build_container
from learner.evidence import Evidence, EvidenceType, ObservationStatus
from learner.graph import KnowledgeEdge, KnowledgeNode
from learner.states import Learner
from learner.types import NodeType
from coach.db import Base, create_session_factory

# Thresholds for mapping judge fraction -> observation status.
CORRECT_AT = 0.8
INCORRECT_BELOW = 0.4
MISCONCEPTION_SCORE_MAX = 0.6


class LearnerEngine:
    def __init__(
        self,
        db_url: Optional[str] = None,
        decomposer: Optional[TaskDecomposer] = None,
    ) -> None:
        url = db_url or learner_db_url()
        self._db_url = url
        self._session_factory, self._engine = create_session_factory(url)
        self.decomposer = decomposer or TaskDecomposer()
        self._schema_ready = False

    # -- session / container --------------------------------------------------

    def _session(self) -> Session:
        if not self._schema_ready:
            # Idempotent create; the runtime path (also used by coach.db.create_schema).
            Base.metadata.create_all(self._engine)
            self._schema_ready = True
        return self._session_factory()

    def _container(self, session: Session):
        return build_container(session)

    # -- learner identity -------------------------------------------------------

    def ensure_learner(self, candidate: str) -> uuid.UUID:
        """Return (and persist) the learner id for a candidate. Idempotent.

        Identity lives on the ``learners.candidate`` column (UNIQUE), so this
        is a single-hop lookup with no separate binding table.
        """
        session = self._session()
        try:
            container = self._container(session)
            existing = container.learner_repository.get_learner_by_candidate(candidate)
            if existing is not None:
                return existing.id
            learner = container.learner_service.create_learner(
                Learner(candidate=candidate, metadata={"candidate": candidate})
            )
            return learner.id
        finally:
            session.close()

    def learner_id(self, candidate: str) -> Optional[uuid.UUID]:
        session = self._session()
        try:
            container = self._container(session)
            learner = container.learner_repository.get_learner_by_candidate(candidate)
            return learner.id if learner is not None else None
        finally:
            session.close()

    # -- bootstrap -----------------------------------------------------------------

    def bootstrap_task(self, task: dict) -> dict:
        """Decompose a picked task and register it in the knowledge graph.

        Idempotent: nodes/edges are looked up before inserting.
        Task->node mapping is ephemeral (derived from ``TaskKnowledge`` at
        submit time); nothing task-like is persisted.
        Returns {"primary_node_id", "primary_node_slug"}.
        """
        knowledge = self.decomposer.decompose(task)
        session = self._session()
        try:
            container = self._container(session)
            node_ids = self._ensure_graph(
                container, knowledge, task.get("skill", "general")
            )
            primary_id = node_ids[knowledge.primary_node_slug]
            return {
                "primary_node_id": str(primary_id),
                "primary_node_slug": knowledge.primary_node_slug,
            }
        finally:
            session.close()

    @staticmethod
    def _ensure_graph(container, knowledge, skill: str) -> dict[str, uuid.UUID]:
        """Upsert decomposed nodes/edges; return slug -> node id."""
        kg = container.knowledge_service
        node_ids: dict[str, uuid.UUID] = {}
        for node in knowledge.nodes:
            existing = kg.get_node_by_slug(node.slug)
            if existing is not None:
                node_ids[node.slug] = existing.id
                continue
            created = kg.create_node(
                KnowledgeNode(
                    type=node.type,
                    slug=node.slug,
                    name=node.name,
                    description=node.description,
                    metadata={"importance": node.importance, "skill": skill},
                )
            )
            node_ids[node.slug] = created.id

        for edge in knowledge.edges:
            src = node_ids[edge.source_slug]
            tgt = node_ids[edge.target_slug]
            if kg.get_edge(src, tgt, edge.edge_type) is None:
                kg.create_edge(
                    KnowledgeEdge(source_node_id=src, target_node_id=tgt, edge_type=edge.edge_type)
                )
        return node_ids

    @staticmethod
    def _ephemeral_targets(knowledge, node_ids) -> list[tuple[uuid.UUID, float]]:
        """Derive (node_id, signal) pairs without persisting tasks/targets.

        Primary node -> 1.0; PROBLEM nodes skipped (not a measured
        competency); others -> max(0.3, importance).
        """
        targets: list[tuple[uuid.UUID, float]] = []
        for node in knowledge.nodes:
            if node.slug == knowledge.primary_node_slug:
                targets.append((node_ids[node.slug], 1.0))
            elif node.type == NodeType.PROBLEM:
                continue
            else:
                targets.append((node_ids[node.slug], max(0.3, node.importance)))
        return targets

    def bootstrap_generated_task(self, task: dict) -> dict:
        """Ensure the remediation target node exists (no task persistence).

        Args:
            task: a generated task dict carrying ``mvp_target_slug``.

        Returns {"target_slug", "target_node_id"}.
        """
        target_slug = task.get("mvp_target_slug")
        if not target_slug:
            raise ValueError("generated remediation task missing mvp_target_slug")

        session = self._session()
        try:
            container = self._container(session)
            kg = container.knowledge_service
            node = kg.get_node_by_slug(target_slug)
            if node is None:
                # Node vanished: fall back to registering under the skill slug.
                skill_slug = self._slugify(task.get("skill", "general"))
                node = kg.get_node_by_slug(skill_slug)
            if node is None:
                raise ValueError(f"target node not found for slug {target_slug!r}")

            return {
                "target_slug": node.slug,
                "target_node_id": str(node.id),
            }
        finally:
            session.close()

    @staticmethod
    def _slugify(text: str) -> str:
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
        return slug[:60] or "general"

    # -- submission ------------------------------------------------------------------

    def record_submission(
        self,
        candidate: str,
        task: dict,
        result,
        coach,
        viewed_hints: Optional[list] = None,
    ) -> dict:
        """Convert a judge result into evidence and run the learning loop."""
        learner_id = self.ensure_learner(candidate)
        knowledge = self.decomposer.decompose(task)
        session = self._session()
        try:
            container = self._container(session)
            node_ids = self._ensure_graph(
                container, knowledge, task.get("skill", "general")
            )
            targets = self._ephemeral_targets(knowledge, node_ids)

            fraction = max(0.0, min(1.0, result.score / result.max_score)) if result.max_score else 0.0
            status = self._observation_status(fraction)

            evidence_ids: list[str] = []
            for node_id, signal in targets:
                ev = Evidence(
                    learner_id=learner_id,
                    node_id=node_id,
                    evidence_type=EvidenceType.CODE,
                    observation_status=status,
                    correctness=fraction,
                    assessor_explanation=coach.feedback if coach else None,
                    assessment_payload={
                        "coach_task_id": task["id"],
                        "score": result.score,
                        "max_score": result.max_score,
                        "fraction": fraction,
                        "hints_used": viewed_hints or [],
                        "rationale": result.rationale,
                    },
                )
                container.evidence_service.add_evidence(ev)
                container.update_service.apply_evidence(ev, signal)
                evidence_ids.append(str(ev.id))

            # Misconception: only when the coach names one and the score is low.
            # Linked to the primary (skill) node so remediation drills the skill,
            # not the misconception node itself.
            primary_node = node_ids.get(knowledge.primary_node_slug)
            misconception = self._maybe_misconception(
                container, candidate, learner_id, task, coach, fraction, evidence_ids,
                skill_node_id=primary_node,
            )

            frontier = container.frontier_service.generate(learner_id, primary_node)
            actions = container.policy_engine.generate(learner_id, frontier)

            return {
                "learner_id": str(learner_id),
                "evidence_ids": evidence_ids,
                "observation_status": status.value,
                "fraction": fraction,
                "frontier": [self._frontier_dict(container, f) for f in frontier],
                "next_action": self._action_dict(container, actions[0]) if actions else None,
                "misconception": misconception,
            }
        finally:
            session.close()

    @staticmethod
    def _observation_status(fraction: float) -> ObservationStatus:
        if fraction >= CORRECT_AT:
            return ObservationStatus.CORRECT
        if fraction <= INCORRECT_BELOW:
            return ObservationStatus.INCORRECT
        return ObservationStatus.PARTIALLY_CORRECT

    def _maybe_misconception(self, container, candidate, learner_id, task, coach, fraction, evidence_ids, skill_node_id=None):
        text = (coach.misconception if coach else "") or ""
        if not text.strip() or fraction >= MISCONCEPTION_SCORE_MAX:
            return None
        slug = self._misconception_slug(text)
        metadata = {}
        if skill_node_id is not None:
            metadata["skill_node_id"] = str(skill_node_id)
        node = container.knowledge_service.get_node_by_slug(slug)
        if node is None:
            node = container.knowledge_service.create_node(
                KnowledgeNode(
                    type=NodeType.MISCONCEPTION,
                    slug=slug,
                    name=f"Misconception: {task['id']}",
                    description=text.strip()[:300],
                    metadata=metadata,
                )
            )
        elif metadata:
            node = container.knowledge_service.update_node(
                node.id, metadata={**(node.metadata or {}), **metadata}
            )
        mc = container.misconception_service.suspect_misconception(learner_id, node.id)
        if evidence_ids:
            container.misconception_service.add_supporting_evidence(mc.id, uuid.UUID(evidence_ids[0]))
        return {"misconception_node_id": str(node.id), "slug": slug, "confidence": mc.confidence}

    @staticmethod
    def _misconception_slug(text: str) -> str:
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        if len(slug) <= 48:
            return slug or "misconception"
        # Truncate on a word boundary so slugs never cut mid-word.
        head = slug[:48]
        cut = head.rfind("-")
        return head[:cut] if cut > 0 else head

    @staticmethod
    def _frontier_dict(container, entry) -> dict:
        node = container.knowledge_repository.get_node(entry.node_id)
        return {
            "node_id": str(entry.node_id),
            "slug": node.slug if node else None,
            "name": node.name if node else None,
            "description": node.description if node else None,
            "priority": entry.priority,
            "reason": entry.reason,
            "status": entry.status.value,
        }

    @staticmethod
    def _action_dict(container, action) -> dict:
        node = container.knowledge_repository.get_node(action.target_node_id)
        return {
            "action_type": action.action_type.value,
            "target_node_id": str(action.target_node_id),
            "slug": node.slug if node else None,
            "name": node.name if node else None,
            "description": node.description if node else None,
            "total_score": action.total_score,
            "rationale": action.rationale,
        }

    # -- snapshot ---------------------------------------------------------------------

    def learner_snapshot(self, candidate: str, limit: int = 8) -> dict:
        learner_id = self.learner_id(candidate)
        if learner_id is None:
            return {"learner_id": None, "states": {}, "frontier_top": [], "misconceptions": [], "next_action": None}

        session = self._session()
        try:
            container = self._container(session)
            states = {}
            for s in container.learner_service.list_learner_states(learner_id):
                node = container.knowledge_repository.get_node(s.node_id)
                slug = node.slug if node else str(s.node_id)
                states[slug] = {
                    "mastery": s.mastery,
                    "uncertainty": s.uncertainty,
                    "status": s.status.value,
                    "evidence_count": s.evidence_count,
                }

            frontier = container.frontier_service.list_frontier(learner_id)[:limit]
            frontier_top = [self._frontier_dict(container, f) for f in frontier]
            misconceptions = [
                {
                    "node_id": str(mc.misconception_node_id),
                    "status": mc.status.value,
                    "confidence": mc.confidence,
                    "slug": container.knowledge_repository.get_node(mc.misconception_node_id).slug
                    if container.knowledge_repository.get_node(mc.misconception_node_id)
                    else None,
                }
                for mc in container.misconception_service.list_all(learner_id)
                if mc.is_active
            ]
            actions = container.policy_engine.generate(learner_id, frontier)
            next_action = self._action_dict(container, actions[0]) if actions else None

            return {
                "learner_id": str(learner_id),
                "states": states,
                "frontier_top": frontier_top,
                "misconceptions": misconceptions,
                "next_action": next_action,
            }
        finally:
            session.close()


def pick_next_task(
    candidate: str,
    session,
    last_submission: Optional[dict] = None,
    engine: Optional[LearnerEngine] = None,
) -> dict | None:
    """Choose the next task to present.

    Hybrid selection (see docs/refactor-plan.md §7):
      1. Pending generated task — an injected remediation task not yet asked
         surfaces first (generated tasks are excluded from the bank picker).
      2. Frontier remediation — when ``last_submission`` is provided, run the
         learner engine and ``plan_remediation``; an actionable gap generates a
         *simpler* task drilling the frontier-top node.
      3. EIG bank picker — ``coach.picker.next_task(session)``.
      4. Done — ``None`` when the bank is exhausted and no remediation remains.

    ``last_submission`` carries ``{"task", "result", "learner_update",
    "learner_snapshot"}`` from a just-recorded submission.
    """
    from coach.picker import next_task as next_task_bank
    from coach.session import task_view

    # 1. Pending generated remediation task first.
    pending = next(
        (t for t in session.tasks if t.get("generated") and t["id"] not in session.asked_task_ids),
        None,
    )
    if pending is not None:
        return task_view(pending, session)

    # 2. Frontier-driven remediation after a submission.
    if last_submission is not None:
        from coach.remediation import plan_remediation

        generated = plan_remediation(
            session,
            last_submission.get("task"),
            last_submission.get("result"),
            last_submission.get("learner_update"),
            last_submission.get("learner_snapshot") or {},
            bridge=engine,
        )
        if generated is not None:
            return task_view(generated, session)

    # 3. EIG bank picker.
    nxt = next_task_bank(session)
    return task_view(nxt, session) if nxt else None


def clear_learner_data(candidate: str, db_url: Optional[str] = None) -> int:
    """Delete all per-learner data for a candidate.

    Returns the total number of rows deleted across all tables. Knowledge
    graph nodes/edges are global and left intact.
    """
    from coach.db import create_session_factory
    from learner.evidence import EvidenceModel
    from learner.states import LearnerKnowledgeStateModel, LearnerModel
    from learner.misconception import LearnerMisconceptionModel
    from learner.frontier import LearnerFrontierModel
    from sqlalchemy import select

    url = db_url or learner_db_url()
    session_factory, _ = create_session_factory(url)
    session = session_factory()
    total = 0
    try:
        learner = session.scalar(
            select(LearnerModel).where(LearnerModel.candidate == candidate)
        )
        if learner is None:
            return 0
        lid = learner.id

        total += session.query(LearnerMisconceptionModel).filter(
            LearnerMisconceptionModel.learner_id == lid
        ).delete(synchronize_session=False)

        total += session.query(LearnerFrontierModel).filter(
            LearnerFrontierModel.learner_id == lid
        ).delete(synchronize_session=False)

        total += session.query(EvidenceModel).filter(
            EvidenceModel.learner_id == lid
        ).delete(synchronize_session=False)

        total += session.query(LearnerKnowledgeStateModel).filter(
            LearnerKnowledgeStateModel.learner_id == lid
        ).delete(synchronize_session=False)

        total += session.query(LearnerModel).filter(
            LearnerModel.id == lid
        ).delete(synchronize_session=False)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return total


# ---------------------------------------------------------------------------
# CLI inspector
#
#   python -m learner.engine <candidate>     print a candidate's snapshot
#   python -m learner.engine --demo           run a canned learner through
#                                             the full loop and print it
#   python -m learner.engine --db <url> ...   override the learner DB
# ---------------------------------------------------------------------------


def _format_snapshot(candidate: str, snap: dict) -> str:
    lines = [f"Learner snapshot for {candidate}"]
    lines.append("states:")
    if not snap["states"]:
        lines.append("  (none — candidate has not answered any scored task)")
    for slug in sorted(snap["states"]):
        s = snap["states"][slug]
        lines.append(
            f"  {slug:<28} mastery={s['mastery']:.3f}  uncertainty={s['uncertainty']:.3f}  "
            f"status={s['status']:<11} evidence={s['evidence_count']}"
        )

    lines.append("frontier_top:")
    if not snap["frontier_top"]:
        lines.append("  (empty)")
    for i, f in enumerate(snap["frontier_top"], 1):
        lines.append(f"  #{i:<2} {f['slug'] or f['node_id']:<28} priority={f['priority']:.3f}  reason={f['reason']}")

    lines.append("misconceptions:")
    if not snap["misconceptions"]:
        lines.append("  (none)")
    for m in snap["misconceptions"]:
        lines.append(f"  - {m['slug'] or m['node_id']}   {m['status']}   confidence={m['confidence']:.2f}")

    na = snap["next_action"]
    if na:
        lines.append(f"next_action: {na['action_type']} -> {na['slug'] or na['target_node_id']} "
                     f"(score={na['total_score']:.3f})")
    else:
        lines.append("next_action: (none)")
    return "\n".join(lines)


def _run_demo(engine: LearnerEngine) -> str:
    """Run one canned candidate through the full loop (fallback decomposer, no API key)."""
    from coach.judge import CoachContent, EvaluationResult

    candidate = "demo@example.com"
    engine.ensure_learner(candidate)

    task = {
        "id": "mi_sys_cache",
        "skill": "ml_systems",
        "type": "code",
        "difficulty": 3,
        "prompt": "Design a cache for model inference results.",
        "max_score": 5,
    }
    engine.bootstrap_task(task)

    # 1. Correct answer -> mastery rises, frontier shifts to gaps.
    good_coach = CoachContent(feedback="Solid design.", misconception="", steps=[])
    engine.record_submission(
        candidate, task,
        EvaluationResult(task["id"], task["skill"], 5, 5, "Clean cache design.", good_coach.to_dict()),
        good_coach,
    )
    # 2. Low score + named misconception -> suspected misconception + probe action.
    bad_coach = CoachContent(feedback="Off base.", misconception="Confused cache eviction with invalidation.", steps=[])
    engine.record_submission(
        candidate, task,
        EvaluationResult(task["id"], task["skill"], 1, 5, "Wrong direction.", bad_coach.to_dict()),
        bad_coach,
    )

    return _format_snapshot(candidate, engine.learner_snapshot(candidate))


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="learner.engine",
        description="Inspect the learner model for a candidate.",
    )
    parser.add_argument("candidate", nargs="?", help="candidate identity (email or guest id)")
    parser.add_argument("--demo", action="store_true", help="run a canned learner through the full loop")
    parser.add_argument("--db", help="learner database URL (defaults to data/coach.db)")
    args = parser.parse_args(argv)

    if args.db:
        os.environ.setdefault("LEARNING_PARTNER_DB_URL", args.db)

    engine = LearnerEngine(db_url=args.db)

    if args.demo:
        print(_run_demo(engine))
        return 0

    if not args.candidate:
        parser.print_help()
        return 2

    snap = engine.learner_snapshot(args.candidate)
    print(_format_snapshot(args.candidate, snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())