"""Decompose a coding task or interview question into a fine-grained knowledge graph.

This is the parent-app side of the integration: the learner model (`learner`)
stores what it is given but never calls an LLM itself. Here we use the same
Gemini client/retry config as the judge to turn a task prompt into concrete
knowledge nodes + edges + a primary target node.

If the LLM call fails or returns invalid JSON, we fall back to a deterministic
skill-level graph (a SKILL node + a PROBLEM node) so `/start` never breaks.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types

from coach.config import MODEL, http_retry_options
from learner.types import EdgeType, NodeType

# Valid edge types in the MVP knowledge graph.
_EDGE_TYPES = {e.value for e in EdgeType}
_NODE_TYPES = {n.value for n in NodeType}

_NODE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "key": types.Schema(type=types.Type.STRING),
        "type": types.Schema(type=types.Type.STRING),
        "name": types.Schema(type=types.Type.STRING),
        "description": types.Schema(type=types.Type.STRING),
        "importance": types.Schema(type=types.Type.NUMBER),
    },
    required=["key", "type", "name"],
)

_EDGE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "source_key": types.Schema(type=types.Type.STRING),
        "target_key": types.Schema(type=types.Type.STRING),
        "edge_type": types.Schema(type=types.Type.STRING),
    },
    required=["source_key", "target_key", "edge_type"],
)

_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "primary_node_key": types.Schema(type=types.Type.STRING),
        "nodes": types.Schema(type=types.Type.ARRAY, items=_NODE_SCHEMA),
        "edges": types.Schema(type=types.Type.ARRAY, items=_EDGE_SCHEMA),
    },
    required=["primary_node_key", "nodes", "edges"],
)

_REMEDIATION_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "prompt": types.Schema(type=types.Type.STRING),
        "difficulty": types.Schema(type=types.Type.INTEGER),
    },
    required=["prompt", "difficulty"],
)

_SYSTEM_PROMPT = """\
You are a knowledge-engineering assistant for a learning system. Given a coding \
task or interview question, decompose the knowledge a learner needs to solve it \
into a small knowledge graph.

Return JSON with three keys:
  "primary_node_key": the key of the single node the task MOST directly measures.
  "nodes": 2-8 items. Each item: {"key", "type", "name", "description", "importance"}.
    - "key" is an ephemeral id for this payload only (e.g. "n0", "n1"). Edges
      reference keys, never names or ids.
    - "type" must be one of: concept, skill, procedure, problem, strategy, misconception, domain.
    - "name" is the stable human-readable label (e.g. "Binary Search CDF").
      Reuse the exact same name+type spelling for the same concept.
    - "importance" is a number in [0, 1] (how central this node is to the task).
  "edges": 1-8 directed relationships between the node keys.
    Each item: {"source_key", "target_key", "edge_type"} where edge_type is one of:
    prerequisite_of, requires, part_of, composed_of, applied_in, contrasts_with,
    commonly_confused_with, generalizes_to, specializes_to, enables, alternative_to.

Keep it concrete and focused on THIS task; do not emit the whole ML canon. The \
primary node should be the skill the answer demonstrates."""

_REMEDIATION_PROMPT = """\
You are a tutor for a learning system. A candidate answered the original task \
incorrectly or with low confidence on a specific knowledge node. Create ONE \
simpler coding task that drills directly into that node so the candidate can \
rebuild the missing skill with a small, focused exercise.

Return JSON with exactly two keys:
  "prompt": the new, simpler coding task prompt (2-6 sentences, self-contained,
    with a clear function signature or spec). Reduce scope versus the original;
    isolate only the target node. Do not reveal the answer.
  "difficulty": an integer in [1, 5] strictly at or below the original task's
    difficulty, reflecting the reduced scope.

The target node description is the thing to drill. Keep the prompt concrete and
answerable in a few minutes."""


@dataclass
class DecomposedNode:
    key: str
    type: NodeType
    name: str
    description: Optional[str] = None
    importance: float = 0.7


@dataclass
class DecomposedEdge:
    source_key: str
    target_key: str
    edge_type: EdgeType


@dataclass
class TaskKnowledge:
    """Result of decomposing a task into graph primitives."""

    task_id: str
    skill: str
    primary_node_key: str
    nodes: list[DecomposedNode] = field(default_factory=list)
    edges: list[DecomposedEdge] = field(default_factory=list)

    @property
    def primary_node(self) -> DecomposedNode | None:
        return next((n for n in self.nodes if n.key == self.primary_node_key), None)


class TaskDecomposer:
    """Turns a task dict (or custom question) into a TaskKnowledge graph."""

    def __init__(self, client: Optional[genai.Client] = None, model: Optional[str] = None) -> None:
        self._client_impl = client
        self._model = model or MODEL

    def decompose(self, task: dict) -> TaskKnowledge:
        prompt = task.get("prompt", "")
        skill = task.get("skill", "general")
        task_id = task.get("id", f"custom_{uuid.uuid4().hex[:8]}")

        # Without an API key there is nothing to call: go straight to the
        # deterministic fallback (also keeps test runs hermetic/fast).
        if not __import__("os").getenv("GOOGLE_API_KEY"):
            return self._fallback(task_id, skill, prompt)

        try:
            knowledge = self._call_llm(prompt, skill)
            return self._validate(task_id, skill, knowledge)
        except Exception:
            # Deterministic fallback: skill node + problem node.
            return self._fallback(task_id, skill, prompt)

    # -- LLM path ---------------------------------------------------------

    def _client(self) -> genai.Client:
        """Shared, lazily-created Gemini client with the project retry config."""
        return self._client_impl or genai.Client(
            api_key=__import__("os").getenv("GOOGLE_API_KEY"),
            http_options=types.HttpOptions(retry_options=http_retry_options()),
        )

    def _call_llm(self, prompt: str, skill: str) -> dict:
        resp = self._client().models.generate_content(
            model=self._model,
            contents=f"Skill: {skill}\n\nTask:\n{prompt}",
            config={
                "system_instruction": _SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_schema": _SCHEMA,
            },
        )
        return json.loads(resp.text)

    def _validate(self, task_id: str, skill: str, payload: dict) -> TaskKnowledge:
        raw_nodes = payload.get("nodes") or []
        raw_edges = payload.get("edges") or []
        primary = str(payload.get("primary_node_key", "") or "").strip()

        nodes: list[DecomposedNode] = []
        by_key: dict[str, DecomposedNode] = {}
        for i, item in enumerate(raw_nodes[:12]):
            ntype = item.get("type")
            if ntype not in _NODE_TYPES:
                ntype = "concept"
            key = str(item.get("key", "") or "").strip() or f"n{i}"
            if key in by_key:
                continue
            name = str(item.get("name") or f"Node {i}").strip()[:255] or f"Node {i}"
            node = DecomposedNode(
                key=key,
                type=NodeType(ntype),
                name=name,
                description=str(item.get("description") or None),
                importance=max(0.0, min(1.0, float(item.get("importance", 0.7)))),
            )
            by_key[key] = node
            nodes.append(node)

        # Ensure primary node exists (fall back to first node if missing).
        if primary not in by_key and nodes:
            primary = nodes[0].key
        if not nodes:
            raise ValueError("decomposition produced no nodes")

        edges: list[DecomposedEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for item in raw_edges[:16]:
            src = str(item.get("source_key", "") or "").strip()
            tgt = str(item.get("target_key", "") or "").strip()
            etype = str(item.get("edge_type", ""))
            if src not in by_key or tgt not in by_key or etype not in _EDGE_TYPES:
                continue
            key = (src, tgt, etype)
            if key in seen:
                continue
            seen.add(key)
            edges.append(DecomposedEdge(src, tgt, EdgeType(etype)))

        return TaskKnowledge(task_id=task_id, skill=skill, primary_node_key=primary,
                             nodes=nodes, edges=edges)

    # -- deterministic fallback -------------------------------------------

    def _fallback(self, task_id: str, skill: str, prompt: str) -> TaskKnowledge:
        skill_name = (skill or "general").strip() or "general"
        skill_node = DecomposedNode(
            key="n0",
            type=NodeType.SKILL, name=skill_name.title(),
            description=f"Skill exercised by {task_id}.", importance=0.8,
        )
        problem_node = DecomposedNode(
            key="n1",
            type=NodeType.PROBLEM, name=f"Task: {task_id}",
            description=prompt[:200], importance=1.0,
        )
        return TaskKnowledge(
            task_id=task_id,
            skill=skill,
            primary_node_key="n0",
            nodes=[skill_node, problem_node],
            edges=[
                DecomposedEdge("n1", "n0", EdgeType.APPLIED_IN),
                DecomposedEdge("n1", "n0", EdgeType.REQUIRES),
            ],
        )

    # -- remediation task generation --------------------------------------

    def generate_remediation_task(
        self,
        node: dict,
        original_task: dict,
        original_fraction: float,
    ) -> dict:
        """Generate a simpler coding task that drills into a specific KG node.

        Args:
            node: the target knowledge node as {"node_id", "name", "description"}.
            original_task: the task the candidate just answered.
            original_fraction: the candidate's 0..1 score on it (drives difficulty).

        Returns a task dict with keys id/skill/type/difficulty/prompt/max_score,
        plus the bookkeeping keys ``generated`` and ``mvp_target_node_id``. Falls
        back to a deterministic re-scoped prompt when no API key is available.
        """
        task_id = f"remed_{uuid.uuid4().hex[:10]}"
        skill = original_task.get("skill", "general")
        base_difficulty = max(1, min(5, int(original_task.get("difficulty", 2))))

        # Reduce difficulty with how poorly the candidate performed, but keep >= 1.
        difficulty = max(1, base_difficulty - 1)
        if original_fraction < 0.4:
            difficulty = max(1, difficulty - 1)

        if not __import__("os").getenv("GOOGLE_API_KEY"):
            prompt = self._fallback_remediation_prompt(node, original_task)
            return self._build_remediation(task_id, skill, difficulty, prompt, node)

        try:
            payload = self._call_remediation_llm(node, original_task)
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("empty remediation prompt")
            llm_difficulty = int(payload.get("difficulty", difficulty))
            difficulty = max(1, min(base_difficulty, llm_difficulty))
            return self._build_remediation(task_id, skill, difficulty, prompt, node)
        except Exception:
            prompt = self._fallback_remediation_prompt(node, original_task)
            return self._build_remediation(task_id, skill, difficulty, prompt, node)

    def _call_remediation_llm(self, node: dict, original_task: dict) -> dict:
        resp = self._client().models.generate_content(
            model=self._model,
            contents=(
                f"Original task:\n{original_task.get('prompt', '')}\n\n"
                f"Target node id: {node.get('node_id')}\n"
                f"Target node name: {node.get('name')}\n"
                f"Target node description: {node.get('description') or ''}"
            ),
            config={
                "system_instruction": _REMEDIATION_PROMPT,
                "response_mime_type": "application/json",
                "response_schema": _REMEDIATION_SCHEMA,
            },
        )
        return json.loads(resp.text)

    @staticmethod
    def _build_remediation(
        task_id: str, skill: str, difficulty: int, prompt: str, node: dict
    ) -> dict:
        return {
            "id": task_id,
            "skill": skill,
            "type": "code",
            "difficulty": difficulty,
            "prompt": prompt,
            "max_score": 5,
            "hints": [],
            "generated": True,
            "mvp_target_node_id": node.get("node_id"),
        }

    @staticmethod
    def _fallback_remediation_prompt(node: dict, original_task: dict) -> str:
        """Deterministic fallback: re-scope the original prompt to the node."""
        node_name = node.get("name") or "this topic"
        return (
            f"Working specifically on: {node_name}.\n"
            f"{node.get('description') or ''}\n"
            f"Write a small, self-contained function that demonstrates correct "
            f"use of {node_name}. Keep it focused and minimal; this is a warm-up "
            f"for: {original_task.get('prompt', '')}"
        ).strip()

    # -- consolidation variant generation -----------------------------------

    def generate_variant_task(
        self,
        node: dict,
        original_task: dict,
        difficulty: int,
    ) -> dict:
        """Generate a similar, high-solvability variant drilling the same node.

        Same shape as remediation tasks (``generated`` + ``mvp_target_node_id``)
        but framed as consolidation, not repair: new surface story, same
        concept, difficulty pre-tuned by ``coach.solvability`` so P(solve)
        lands near 0.8. Falls back deterministically without an API key.
        """
        task_id = f"consol_{uuid.uuid4().hex[:10]}"
        skill = original_task.get("skill", "general")
        difficulty = max(1, min(5, int(difficulty)))

        if not __import__("os").getenv("GOOGLE_API_KEY"):
            prompt = self._fallback_variant_prompt(node, original_task)
            return self._build_remediation(task_id, skill, difficulty, prompt, node)

        try:
            resp = self._client().models.generate_content(
                model=self._model,
                contents=(
                    f"Original task:\n{original_task.get('prompt', '')}\n\n"
                    f"Target node id: {node.get('node_id')}\n"
                    f"Target node name: {node.get('name')}\n"
                    f"Target node description: {node.get('description') or ''}\n"
                    f"Desired difficulty (1-5): {difficulty}\n\n"
                    "Create ONE similar coding task on the same concept with a "
                    "fresh surface story at the desired difficulty. Keep it "
                    "self-contained with a clear function signature. Do not "
                    "reveal the answer."
                ),
                config={
                    "system_instruction": _REMEDIATION_PROMPT,
                    "response_mime_type": "application/json",
                    "response_schema": _REMEDIATION_SCHEMA,
                },
            )
            payload = json.loads(resp.text)
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("empty variant prompt")
            return self._build_remediation(task_id, skill, difficulty, prompt, node)
        except Exception:
            prompt = self._fallback_variant_prompt(node, original_task)
            return self._build_remediation(task_id, skill, difficulty, prompt, node)

    @staticmethod
    def _fallback_variant_prompt(node: dict, original_task: dict) -> str:
        node_name = node.get("name") or "this topic"
        return (
            f"Follow-up practice on: {node_name}.\n"
            f"{node.get('description') or ''}\n"
            f"Write a small self-contained function similar to, but different from, "
            f"the previous exercise on {node_name}. Original for reference: "
            f"{original_task.get('prompt', '')}"
        ).strip()