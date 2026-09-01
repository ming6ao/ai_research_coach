# AI Learning Partner — MVP

Core product model:

```
Knowledge Graph → Learner Model → Evidence → Learning Frontier
```

- **Knowledge Graph** — domain knowledge: concepts, skills, procedures, problems, strategies, misconceptions, domains, and the relationships between them.
- **Learner Model** — what we believe about a specific learner's mastery/uncertainty of each knowledge node.
- **Evidence** — immutable observations from learner interactions that support or contradict learner-model estimates.
- **Learning Frontier** — the learner-specific set of nodes that are candidates for further learning or assessment.

This repository currently implements:
- **Stage 1**: persistent Knowledge Graph
- **Stage 2**: persistent Learner Model
- **Stage 3**: immutable learner evidence
- **Stage 4**: assessment tasks & targets
- **Stage 5**: deterministic learner-state updates from evidence
- **Stage 6**: learner misconceptions
- **Stage 7**: learner-specific Learning Frontier
- **Stage 8**: adaptive next-action selection
- **Stage 9**: end-to-end adaptive learning loop (orchestrator)
- **Stage 10**: deterministic evaluation/replay harness

## Stage 1 scope

- `KnowledgeNode` / `KnowledgeEdge` domain models (Pydantic)
- SQLAlchemy 2.x models + Alembic migration (portable SQLite by default)
- Repository API (create/get/update/delete nodes, create/get edges, outgoing/incoming/related edges)
- Graph traversal utilities (prerequisites, dependents, neighbors, descendants, ancestors) in application code — no recursive SQL
- Validation: no self-edges, referenced nodes must exist, unique `(source, target, edge_type)`, unique slugs
- Seed graph: **Weighted Sampling From Scratch**

Explicitly **not** in this stage: learner state, evidence, assessment tasks, adaptive policy, LLM integration.

## Stage 2 scope (Learner Model)

- `Learner` — who is being coached (id, metadata, timestamps).
- `LearnerKnowledgeState` — per-(learner, node) belief: mastery, uncertainty,
  competency dimensions, evidence count, status, timestamps. All scores in [0, 1].
- **Semantic rule: unknown ≠ low mastery.** An unseen node is a *neutral prior*
  (mastery 0.5, uncertainty 1.0, evidence_count 0, status `unknown`) — never low
  scores. This is enforced by a model validator and by `list_low_mastery_nodes`
  (threshold is strictly below 0.5, so `unknown` is never listed as low).
- Lazy state creation: state rows are created only when a learner encounters a
  node (`initialize_state`), never eagerly for the whole graph.
- Deterministic derived helpers on `LearnerKnowledgeState`: `is_unknown`,
  `is_uncertain`, `is_low_mastery`, `is_mastered`, `is_ready_for_assessment`,
  `confidence_level` (= 1 − uncertainty), and `derive_status(...)`.
- No mastery updates from evidence yet (that is a later stage).

Explicitly **not** in this stage: evidence, assessment tasks, frontier, adaptive policy.

## Stage 3 scope (Immutable Evidence)

- `Evidence` — an **immutable, append-only** observation of learner performance
  on a knowledge node: learner, session, interaction, assessment task, node,
  evidence type, observation status, correctness / reasoning quality /
  independence / confidence, behavior + assessor explanation, payload, timestamp.
- Evidence types: `answer`, `explanation`, `code`, `debugging`, `prediction`,
  `trace`, `teach_back`, `self_report`, `conversation`.
- Observation statuses: `correct`, `incorrect`, `partially_correct`,
  `not_observed`, `ambiguous`.
- **Semantic rule: not_observed is not incorrect.** A `not_observed` record
  cannot carry a correctness score (model-validated) and is counted separately
  in summaries — never as incorrect, never in the correctness averages.
- Immutability enforced two ways: the Pydantic model is `frozen=True`, and the
  repository is append-only (`add_evidence` only; no update/delete). Mistakes
  are corrected by writing a new superseding record, never by editing history.
- Filtering by learner, node, type, status, and time range.
- `EvidenceService.summarize(...)` aggregates counts and averages for a
  (learner, node) pair **without** changing any learner-model estimate.

Explicitly **not** in this stage: updating learner mastery from evidence,
assessment tasks, frontier, adaptive policy.

## Stage 4 scope (Assessment Tasks & Targets)

Answers: *"What task can provide evidence about which competencies?"*

- `AssessmentTask` — an instrument given to a learner: id, task type, title,
  prompt, difficulty [0, 1], metadata, timestamps.
- Task types: `coding`, `explanation`, `debugging`, `prediction`, `design`,
  `multiple_choice`, `trace`, `teach_back`.
- `AssessmentTarget` — a link from a task to a knowledge node: task_id,
  node_id, `target_role`, `expected_signal_strength` [0, 1], metadata.
- Target roles: `primary` (task directly measures this node), `secondary`
  (exercised incidentally), `prerequisite` (must be known to attempt the task),
  `diagnostic` (probes competing misconceptions).
- One target per (task, node); a task may target many nodes; many tasks may
  target the same node.
- Repositories: `AssessmentTaskRepository` (create/get/update/list tasks,
  find tasks for a node) and `AssessmentTargetRepository` (add/remove targets,
  list targets for a task, list tasks targeting a node).
- Seed task: **"Implement weighted sampling from scratch"** (coding, difficulty
  0.65) with 8 targets covering the seed graph's skills/concepts.

Explicitly **not** in this stage: assessment scoring, producing evidence from
tasks, mastery updates, frontier, adaptive policy.

## Stages 5-10: adaptive learning loop

Stages 5–8 build the "brain" that turns evidence into learner beliefs, a
frontier, and a next action. Stage 9 wires it into one loop; Stage 10 makes it
measurable.

### Stage 5 — deterministic state updates (`domain/update.py`)

- `UpdateEngine.apply(previous_state, evidence, signal_strength)` — pure, testable.
- Base performance from status: correct→1.0, incorrect→0.0, partially_correct→0.5.
- `effective_weight = expected_signal_strength * evidence_quality`, where
  `evidence_quality` averages **only observed** dimensions (confidence 0.5,
  reasoning 0.3, independence 0.2).
- Mastery moves `learning_rate * weight` of the way toward performance; a single
  observation can never drive mastery to 0 or 1.
- Uncertainty shrinks multiplicatively; `ambiguous`/`not_observed` are ignored.
- `self_report` moves only `self_confidence`; `conversation` is low-strength.
- Status thresholds live in `UpdateConfig` (configurable, not hardcoded).
- Every applied update is persisted to `learner_state_updates` (audit trail) via
  `LearnerUpdateService`.

### Stage 6 — misconceptions (`domain/misconception.py`, `services/misconception.py`)

- `LearnerMisconception`: learner-specific hypothesis tied to a knowledge node
  of type `misconception`. Statuses: suspected → confirmed → resolving → resolved.
- Never auto-created from an incorrect answer; requires explicit diagnostic
  evidence (`suspect_misconception`).
- Evidence links with relationship: supporting / contradicting / resolving.
- `MisconceptionService`: `suspect_misconception`, `add_supporting_evidence`,
  `add_contradicting_evidence`, `resolve_misconception`, `list_active_misconceptions`.

### Stage 7 — Learning Frontier (`domain/frontier.py`, `services/frontier.py`)

- `LearnerFrontier` entries with `priority`, `reason`, `source_node_id`, `status`.
- `FrontierService.generate(...)` sources candidates from prerequisites, related
  nodes, high-uncertainty states, low-mastery states, task targets, and adjacent
  nodes.
- `priority = relevance * uncertainty * importance * prerequisite_factor`
  (all in `FrontierConfig`).
- Filtering: mastered + low-uncertainty nodes are excluded unless required by a
  task or explicitly requested.

### Stage 8 — next-action selection (`domain/action.py`, `services/policy.py`)

- `CandidateAction` with `information_gain`, `learning_value`, `goal_relevance`,
  `difficulty_fit`, `frustration_cost`, `redundancy_cost`, `total_score`.
- `total_score = information_gain + learning_value + goal_relevance +
  difficulty_fit - frustration_cost - redundancy_cost`.
- Behavior: mastery high/uncertainty low → recap; high mastery/high uncertainty
  → probe; low mastery/low uncertainty → teach (explain/code); low/low-unc →
  diagnose (probe); suspected misconception → misconception_probe; missing
  prerequisite → priority.

### Stage 9 — orchestrator (`services/orchestrator.py`)

`LearningOrchestrator.process(interaction)` runs the full loop:
1. receive interaction → 2. persist as evidence → 3. resolve relevant nodes →
4. resolve task → 5. `EvidenceAssessor.assess(...)` → 6. persist immutable
evidence → 7. update learner state → 8. update misconceptions → 9. update
frontier → 10. generate actions → 11. select next → 12. return structured result.

The tutor response is **not** responsible for modifying the learner model:
`learner response → evidence → learner-model update → policy → tutor response`.

### Stage 10 — replay harness (`harness/`)

- JSON scenarios under `harness/scenarios/`: learner, starting state, knowledge
  graph, task, interaction script, and qualitative assertions.
- `ReplayEngine` replays through the orchestrator; `checks.py` asserts broad
  outcomes (no exact floats): status, mastery/uncertainty bounds, dimension
  bounds, `not_observed_not_incorrect`, frontier include/exclude/rank, action
  targeting, misconception activity.
- Six bundled scenarios: strong, beginner, strong-concepts-weak-implementation,
  CDF misconception, overconfident, underconfident.
- Run with `python -m learning_partner eval`.

## Architecture

```
learning_partner/
├── domain/        # Pure Pydantic models, enums, errors, repository Protocols (no DB imports)
├── storage/       # SQLAlchemy engine/session, ORM models, repository implementation
├── services/      # KnowledgeGraphService facade + traversal logic (application code)
├── seed/          # Idempotent seed graphs
└── tests/         # pytest suite (in-memory SQLite)
```

Boundaries:

- **Domain never imports storage.** Domain defines repository *interfaces* (`domain/interfaces.py`); storage implements them. Application logic (traversal, later learner-model math) lives in `services/`, not in SQL.
- **Repositories are dumb CRUD.** No domain logic in queries.
- **No DB-specific features.** UUIDs stored as 36-char strings; timestamps stored as naive UTC and normalized to tz-aware UTC at the boundary; JSON via SQLAlchemy's portable `JSON` type. Anything that would be PostgreSQL-specific is avoided.

## Schema

`knowledge_nodes`

| column | type | notes |
|--------|------|-------|
| id | String(36) | UUID |
| type | String(32) | concept/skill/procedure/problem/strategy/misconception/domain |
| slug | String(255) | unique |
| name | String(255) | |
| description | Text | nullable |
| metadata | JSON | |
| version | Integer | auto-increments on update |
| status | String(32) | draft/active/archived |
| created_at | DateTime | UTC |
| updated_at | DateTime | UTC |

`knowledge_edges`

| column | type | notes |
|--------|------|-------|
| id | String(36) | UUID |
| source_node_id | String(36) | FK → knowledge_nodes.id |
| target_node_id | String(36) | FK → knowledge_nodes.id |
| edge_type | String(64) | prerequisite_of/requires/part_of/… |
| weight | Float | [0, 1] |
| metadata | JSON | |
| created_at | DateTime | UTC |

Unique constraint on `(source_node_id, target_node_id, edge_type)`.

`learners`

| column | type | notes |
|--------|------|-------|
| id | String(36) | UUID |
| metadata | JSON | |
| created_at | DateTime | UTC |
| updated_at | DateTime | UTC |

`learner_knowledge_states` — one row per (learner, node); unique on `(learner_id, node_id)`

| column | type | notes |
|--------|------|-------|
| id | String(36) | UUID |
| learner_id | String(36) | FK → learners.id |
| node_id | String(36) | FK → knowledge_nodes.id |
| mastery | Float | point-estimate belief, [0, 1] |
| uncertainty | Float | spread of belief, [0, 1] (1.0 = max) |
| conceptual / procedural / implementation / transfer / fluency / self_confidence | Float | competency dimensions, [0, 1] |
| evidence_count | Integer | ≥ 0 |
| last_assessed_at / last_decay_at | DateTime | nullable |
| status | String(32) | unknown/uncertain/developing/proficient/mastered |
| metadata | JSON | |
| created_at / updated_at | DateTime | UTC |

`evidence` — immutable, append-only

| column | type | notes |
|--------|------|-------|
| id | String(36) | UUID |
| learner_id | String(36) | FK → learners.id |
| session_id / interaction_id / assessment_task_id | String(36) | nullable |
| node_id | String(36) | FK → knowledge_nodes.id |
| evidence_type | String(32) | answer/explanation/code/debugging/prediction/trace/teach_back/self_report/conversation |
| observation_status | String(32) | correct/incorrect/partially_correct/not_observed/ambiguous |
| correctness | Float | nullable, [0, 1] |
| reasoning_quality / independence / confidence | Float | nullable, [0, 1] |
| observed_behavior | Text | nullable |
| assessor_explanation | Text | nullable |
| assessment_payload | JSON | |
| created_at | DateTime | UTC |

No update/delete operations exist for this table. Correcting a record means
writing a new record that supersedes it.

`assessment_tasks`

| column | type | notes |
|--------|------|-------|
| id | String(36) | UUID |
| task_type | String(32) | coding/explanation/debugging/prediction/design/multiple_choice/trace/teach_back |
| title | String(255) | |
| prompt | Text | |
| difficulty | Float | [0, 1] |
| metadata | JSON | |
| created_at / updated_at | DateTime | UTC |

`assessment_targets` — one row per (task, node); unique on `(task_id, node_id)`

| column | type | notes |
|--------|------|-------|
| id | String(36) | UUID |
| task_id | String(36) | FK → assessment_tasks.id |
| node_id | String(36) | FK → knowledge_nodes.id |
| target_role | String(32) | primary/secondary/prerequisite/diagnostic |
| expected_signal_strength | Float | [0, 1] |
| metadata | JSON | |
| created_at / updated_at | DateTime | UTC |

### Stages 5-10 tables

`learner_state_updates` — audit trail; every state update traceable to evidence

| column | notes |
|--------|-------|
| id / learner_id / node_id / evidence_id | UUIDs (evidence_id FK → evidence) |
| previous_mastery / new_mastery / previous_uncertainty / new_uncertainty | Float |
| update_reason | Text (e.g. "correct code evidence (weight=0.900)") |
| created_at | DateTime UTC |

`learner_misconceptions`

| column | notes |
|--------|-------|
| id / learner_id / misconception_node_id | UUIDs (node FK → knowledge_nodes) |
| confidence | Float [0, 1] |
| status | suspected/confirmed/resolving/resolved |
| first_detected_at / last_observed_at / resolved_at | DateTime UTC |
| notes / metadata | nullable |

`misconception_evidence` — join table, unique on `(misconception_id, evidence_id)`

| column | notes |
|--------|-------|
| id / misconception_id / evidence_id | UUIDs |
| relationship | supporting/contradicting/resolving |
| created_at | DateTime UTC |

`learner_frontier` — unique on `(learner_id, node_id)`

| column | notes |
|--------|-------|
| id / learner_id / node_id / source_node_id | UUIDs |
| priority | Float [0, 1] |
| reason | prerequisite/related/uncertain/low_mastery/task_required/adjacent/explicit_request |
| status | candidate/active/deferred/completed |
| created_at / updated_at | DateTime UTC |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Apply migrations
alembic upgrade head

# Seed sample data
python -m learning_partner seed

# Run tests
python -m pytest
```

Override the database URL with `LEARNING_PARTNER_DB_URL` (default `sqlite:///data/knowledge_graph.db`).

## How to add a new learner scenario (Stage 10)

Scenarios live in `learning_partner/harness/scenarios/*.json` and are auto-loaded
by the test suite and `python -m learning_partner eval`.

A scenario has four parts:

```json
{
  "name": "X_weighted_sampling_some_profile",
  "starting_states": {
    "normalize_weights": {"mastery": 0.9, "uncertainty": 0.1, "evidence_count": 8, "status": "mastered"}
  },
  "interactions": [
    {
      "message": "any text the fake assessor can match on",
      "evidence": [
        {"node_slug": "construct_cdf", "evidence_type": "code",
         "observation_status": "correct", "correctness": 1.0, "confidence": 1.0}
      ]
    }
  ],
  "assertions": [
    {"kind": "status", "node": "construct_cdf", "expect": "proficient"},
    {"kind": "frontier_rank_above", "above": ["binary_search_cdf"], "below": ["normalize_weights"]},
    {"kind": "not_observed_not_incorrect", "node": "handle_boundaries"}
  ]
}
```

- `starting_states` is optional; omit it for a pure beginner. Keys are node slugs.
- `interactions` map 1:1 onto orchestrator turns; the `evidence` list is what the
  deterministic `ScriptedEvidenceAssessor` returns for that turn.
- `assertions` are qualitative — no exact floats. Supported kinds:
  `status`, `status_not`, `mastery_above`, `mastery_below`, `uncertainty_below`,
  `evidence_count_above`, `dimension_above`, `dimension_below`,
  `not_observed_not_incorrect`, `frontier_includes`, `frontier_excludes`,
  `frontier_rank_above`, `action_not_targets`, `action_targets_any`,
  `misconception_active`, `misconception_confirmed`, `misconception_probe_action`.

To add one: copy an existing scenario, adjust the profile + interactions +
assertions, then run `python -m learning_partner eval`. The harness is intended
to be the main evaluation framework for future learner-model changes.

## Traversal semantics

- `direct_prerequisites(X)` / `ancestors(X)`: nodes that must be known before X —
  `A --prerequisite_of--> X` or `X --requires--> A`.
- `direct_dependents(X)` / `descendants(X)`: nodes that depend on X —
  `X --prerequisite_of--> B` or `B --requires--> X`.
- `neighbors(X)`, `get_related_nodes(X)`: any edge type, either direction.
- Only `prerequisite_of` and `requires` edges participate in prerequisite/dependent
  traversal; the other edge types (`enables`, `part_of`, `applied_in`, …) still count
  as neighbors.

## Repository API

| Method | Purpose |
|--------|---------|
| `create_node(node)` | Insert node; rejects duplicate slug |
| `get_node(node_id)` / `get_node_by_slug(slug)` | Fetch node |
| `update_node(node_id, **changes)` | Patch; bumps `version`, refreshes `updated_at` |
| `delete_node(node_id, force=False)` | Refuses while edges reference it unless `force=True` |
| `create_edge(edge)` | Validates self-edge + referenced nodes + uniqueness |
| `get_edge(source, target, type)` | Lookup |
| `get_outgoing_edges(node_id)` / `get_incoming_edges(node_id)` | Directional lookups |
| `get_related_nodes(node_id)` | Any-edge connected nodes |

## Learner model API (`LearnerModelService`)

| Method | Purpose |
|--------|---------|
| `create_learner()` / `get_learner(id)` | Learner CRUD |
| `get_state(learner_id, node_id)` | Returns persisted state or `None` |
| `initialize_state(learner_id, node_id)` | Lazily create the neutral `unknown` state (idempotent) |
| `upsert_state(state)` | Insert or update state for (learner, node); validates learner + node exist |
| `list_learner_states(learner_id)` | All states for a learner |
| `list_uncertain_nodes(learner_id)` | States that are unknown or uncertain |
| `list_low_mastery_nodes(learner_id)` | States with mastery < 0.5 (never includes `unknown`) |
| `list_mastered_nodes(learner_id)` | States classified `mastered` |

State rows are created **lazily** — never eagerly for the whole graph.

## Evidence API (`EvidenceService`)

| Method | Purpose |
|--------|---------|
| `add_evidence(evidence)` | Append an immutable record (only write path) |
| `get_evidence(id)` | Fetch a record |
| `list_evidence_for_learner(id, filters)` | Records for a learner |
| `list_evidence_for_node(id, filters)` | Records for a node |
| `list_evidence_for_interaction(id, filters)` | Records for an interaction |
| `count_evidence(filters)` | Count matching records |
| `get_latest_evidence(filters)` | Most recent matching record |
| `summarize(learner_id, node_id)` | Aggregated counts + averages (no learner-model mutation) |

`EvidenceFilter` fields: `learner_id`, `node_id`, `evidence_type`,
`observation_status`, `from_time`, `to_time`.

## Assessment API (`AssessmentService`)

| Method | Purpose |
|--------|---------|
| `create_task(task)` / `get_task(id)` / `update_task(id, **changes)` | Task CRUD |
| `list_tasks(task_type=None)` | List tasks, optionally by type |
| `find_tasks_for_node(node_id, role=None)` | Tasks targeting a node |
| `add_target(task_id, node_id, role, strength, metadata=None)` | Attach a target (validates task + node exist) |
| `remove_target(task_id, node_id)` | Detach a target |
| `list_targets_for_task(task_id, role=None)` | Targets of a task, optionally by role |
| `list_tasks_targeting_node(node_id, role=None)` | Tasks targeting a node (via target repo) |

## Seed graph: Weighted Sampling From Scratch

14 nodes, 13 edges. Core problem: implement weighted sampling given only weights and a uniform random source.

```
probability ──prerequisite_of──▶ weighted_distribution ──enables──▶ normalize_weights
prefix_sum ──prerequisite_of──▶ cumulative_distribution
prefix_sum ──enables──▶ construct_cdf
uniform_random_variable ──enables──▶ map_sample_to_interval
construct_cdf ──enables──▶ map_sample_to_interval
binary_search_cdf ──enables──▶ map_sample_to_interval
handle_boundaries ──enables──▶ binary_search_cdf
normalize_weights ──requires──▶ probability
weighted_sampling_from_scratch ──requires──▶ {normalize_weights, construct_cdf, generate_uniform_sample, map_sample_to_interval}
```

## Next stage (recommended)

The MVP loop is functional end to end. Natural next steps:

- **LLM-backed `EvidenceAssessor`** — replace the deterministic fakes with a real
  implementation while keeping the `EvidenceAssessor` boundary unchanged.
- **A richer assessment-task catalog** and per-task evidence production with
  signal weights.
- **Frontier/action tuning** via the Stage 10 harness as the primary regression
  framework (add scenarios, tune `UpdateConfig`/`FrontierConfig`/`PolicyConfig`).
- **Interaction persistence** (raw transcripts) and candidate-action persistence
  for debugging.

## Design decisions

- Domain layer uses Pydantic models with `extra="forbid"` so invalid payloads fail early.
- IDs are UUIDs; timestamps are timezone-aware UTC at the domain boundary.
- Deletion is safe by default: a node with edges cannot be deleted without `force=True`, which also removes its edges.
- Seed data is idempotent: re-running adds nothing.
- Traversal is iterative BFS in `services/`, keeping the DB portable (no recursive CTEs).
- The learner model is a separate aggregate from the knowledge graph (own tables, own repository, own service).
- "Unknown" is a neutral prior enforced at the model boundary: constructing an `unknown` state with nonzero evidence or non-neutral mastery is a `ValidationError`.
- State is created lazily per encountered node, never eagerly for the whole graph.
- Derived semantics (`list_low_mastery_nodes`, `list_uncertain_nodes`, `list_mastered_nodes`, readiness, confidence) are computed in Python from stored scores — never in SQL.
- Evidence is immutable at two levels: the domain model is `frozen=True`, and the repository exposes no update/delete. Corrections are new records.
- "not_observed" is a first-class status, distinct from "incorrect": such records cannot carry a correctness score and are excluded from correctness aggregations.
- Assessment tasks are separate from the knowledge graph and the learner model; targets are explicit (task, node, role, signal strength) so scoring can later emit per-node evidence weighted by role.
- The mastery update is a simple confidence-weighted moving update (Stage 5) — transparent and testable, with all thresholds in config objects. No Bayesian/IRT/ML yet.
- Every state update is audited to `learner_state_updates` with the evidence id that caused it (traceability).
- Misconceptions require explicit diagnostic evidence; an incorrect answer alone never creates one.
- The frontier and next-action selection are deterministic, config-driven heuristics so behavior can be inspected and replayed.
- The tutor response is decoupled from the learner model: the orchestrator never lets a generated message mutate beliefs — evidence does.