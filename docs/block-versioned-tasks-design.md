# Code-block tasks with version chains (design)

Status: proposed.

Removes `hints`, `cluster_id`, and `followups_json` everywhere and replaces the
single-question task with a **code block** model:

- A task is a code block: one task-level `scaffold` covering a set of related
  functions (`parts`). Parts carry **no** scaffold and **no** hints.
- A single submission fills the whole block; the judge returns **per-part
  scores**; each part's primary tag updates the belief system independently.
- Tasks can be linked into **version chains**: a later version modifies the
  same code and is evaluated on its *own* criteria, with the predecessor's
  submitted answer carried forward as context (e.g. implement a bounded queue,
  then make it thread-safe).

## 1. Data model (`tasks` table)

Dropped columns (added to `_DROPPED_TASK_COLUMNS` in `coach/db.py`):
`hints_json`, `cluster_id`, `followups_json`.

Added columns:

- `parts_json` (`TEXT DEFAULT '[]'`) — a part is
  `{key, prompt, tags, max_score, difficulty}`. No per-part scaffold, no hints.
  `key` is unique within the block; `prompt` required; `tags` taxonomy-validated;
  `max_score` 1–100; `difficulty` 1–5.
- `version_index` (`INTEGER DEFAULT 1`), `depends_on_task_id` (`TEXT NULL`),
  `version_root_id` (`TEXT NULL`).

Version semantics:

- Root version: `version_index=1`, `depends_on_task_id=NULL`,
  `version_root_id` = own id.
- Successor: `version_index=n`, `depends_on_task_id` = previous version's id,
  `version_root_id` = chain root's id.
- `parent_task_id` stays reserved for remediation bookkeeping (not reused).

Block scaffold: one task-level `scaffold` covers all parts. If omitted,
`session.py` composes it from part prompts (regex `def name(...)` per part,
fallback `def {key}(*args): ...`). Empty `parts` = legacy single-question task
(used by generated/remediation tasks; treated as one implicit part at
judge/belief time).

Migration: `seed_question_bank` additionally deletes `source='seed'` rows whose
id is not in the new catalog, so no manual `--reset` is required.

## 2. Seed catalog restructure (`coach/seed_bank.py`)

`SEED_CATALOG` entries become blocks (no `cluster`/`followups`/`hints`); the
~30 seeds regroup into **13 blocks + 3 versioned chains**. Multi-function
prompts (softmax+log_softmax, quantize+dequantize) split into one part per
function. Parts keep their original tags so the union still covers all 46 fine
tags / 11 families (enforced by the existing coverage test).

| Block | Parts | Versions |
|---|---|---|
| `transformer_decode` | softmax, log_softmax, attention, kv_cache | v1 implement; **v2 add causal `mask` param to attention** |
| `training_step` | bp_step, adam_step, lr_at_step | single |
| `regression_fit` | fit_linear, ridge_gd | v1 OLS; **v2 add ridge regularization + overfitting check** |
| `model_selection` | stratified_kfold_splits, grid_search | single |
| `classifier_prep` | balance_by_oversampling, knn_predict | single |
| `dim_reduction` | pca, kmeans | single |
| `tree_interpretability` | best_gini_split, permutation_importance | single |
| `generalization_monitoring` | drift_scores, zscore_anomalies | single |
| `stats_inference` | bootstrap_ci, ttest | single |
| `llm_lifecycle` | bpe_merge, retrieve, finetune_head, quantize_int8/dequantize_int8 | single |
| `deep_architectures` | conv2d_single, lstm_cell | single |
| `data_pipeline` | etl_pipeline, BoundedQueue | **v1 plain bounded queue; v2 thread-safe (Lock + Conditions, block on full/empty)** |
| `eval_metrics` | binary_metrics, train_test_gap | single |

Every catalog function appears in exactly one block: the 30 seed rows' 32
functions partition cleanly into these 13 blocks (a function is never shared
across blocks, so coverage and `depends_on_task_id` lookups stay unambiguous).
The three functions that straddled blocks in earlier drafts now land in a
single block each: `binary_metrics` and `train_test_gap` in `eval_metrics`,
`drift_scores` in `generalization_monitoring`.

Versioned successors are separate catalog entries with slug suffixes
(`thread_queue`, `thread_queue_safe`, …) linked via `depends_on_task_id`.

## 3. Backend changes

- `coach/judge.py` — `_SCHEMA` gains required `parts: [{key, score, rationale}]`.
  `EvaluationResult` carries `parts`; top-level `score`/`max_score` = sums
  (aggregate fraction). System prompt: "score each listed function
  independently 0..max; keys must match." For version successors the user
  message includes the predecessor's submitted code as "previous implementation
  this builds on". LLM-failure fallback assigns `0.5 * max_score` per part.
- `backend/v1/sessions.py:submit_answer` — per-part belief loop: each part's
  `obs = effective_score(part_fraction)` updates that part's `tag_states` +
  `family_states` (its own `difficulty`); **global ability updates once** with
  the aggregate fraction. No hints. Step row: aggregate score/max/fraction;
  per-part scores ride in `result_json`. `last_submission` now carries
  `"answer"` (for code carry-forward).
- `coach/selection.py` — delete `_curated_followup`; add `_version_successor`:
  after a submission (and on resume, via hydrated `session.results[-1]`),
  return the unasked task whose `depends_on_task_id` == last answered id. New
  order: pending-generated → **version successor** → remediation → EIG bank →
  challenge. `pick_next_task` gains optional `session_id` to fetch predecessor
  code from `session_steps` on resume (helper `coach.steps.answer_for_task`).
- `coach/picker.py` — exclude non-root versions (`depends_on_task_id` set) from
  bank candidates; `expected_time` scales by `max(1, len(parts))`.
- `coach/session.py` — `task_view` emits `parts`, aggregate `max_score`,
  composed `scaffold`; for successors adds `previous_code`, `version_index`,
  `version_total`, `depends_on_task_id`. No hints/cluster_id. `Session` drops
  `viewed_hints`/`hints_used`.
- `coach/tasks.py` — model + `parse_parts`/`validate_parts`;
  `create_task`/`update_task`/`task_to_dict` handle parts + version fields;
  block `tags` auto-derived from parts when omitted; hints/cluster/followups
  removed.
- `backend/v1/schemas.py` — remove `hints`/`cluster_id`/`followups`; add
  `parts`, `version_index`, `depends_on_task_id`, `version_root_id` to
  Task/AdminSeed schemas; `AnswerSubmitRequest`/`RedoRequest` drop
  `hints_used`.
- `coach/admin_tables.py` — tasks registry columns → `parts_json`,
  `version_index`, `depends_on_task_id`, `version_root_id`; `_update_task`
  validates parts instead of hints/cluster/followups.
- `coach/score.py` / `solvability.py` — `effective_score(fraction)` (no
  penalty), remove `DEFAULT_HINT_WEIGHT`, drop `hint_penalty` param from
  solvability.
- Delete `coach/hints.py` (`select_hints`, `hint_penalty`,
  `next_hidden_hint`) — dead after the above.
- `coach/remediation.py` / `task_decomposer.py` — drop all hint
  generation/sanitization and `hints=` persistence; generated tasks persist
  with empty parts.
- `coach/steps.py` / `shares.py` — backfill uses `observation = raw_fraction`;
  keep `hints_used` column for legacy, callers pass `[]`.

## 4. Frontend changes

- `client.ts` — delete `Hint`; `Task` gains `parts?: TaskPart[]`,
  `previous_code?`, `version_index?`, `version_total?`, `depends_on_task_id?`;
  `TaskPart = {key, prompt, max_score, difficulty, tags}`; create/patch bodies
  gain `parts` + version fields and lose hints/cluster/followups; `submit`
  drops `hints_used`.
- Delete `TaskPanel/HintSection.tsx` (hints UI gone).
- `ChatView.tsx` — remove HintSection/reveal/viewed; editor initializes from
  `previous_code ?? scaffold`; prompt bubble shows block prompt + each part's
  question ("1. softmax — …"); coaching bubble unchanged.
- `NewSeedForm.tsx` — remove hint editor + cluster_id; add a parts editor
  (repeatable key/prompt/max_score/difficulty/tags) and optional version
  fields.

## 5. Tests & docs

- Delete `test_hints.py`, `test_curated_followups.py`.
- Rewrite `test_seed_bank.py`, `test_admin_tables.py`, `test_reset.py`
  (parts/versions, no hints/cluster/followups).
- Update `test_score.py`, `test_remediation.py`, `test_tasks_db.py`,
  `test_assessment_flow.py`, `test_picker*.py` for hint removal.
- New tests: judge per-part schema; per-part belief updates;
  `_version_successor` ordering + code carry-forward into `task_view` and judge
  context; scaffold auto-composition; parts validation.
- Update `AGENTS.md` (remove hints/followups/cluster; document parts + version
  chains + per-part scoring).

## 6. Execution order

1. `coach/score.py`, `coach/db.py`, `coach/tasks.py` (model + parts/versions)
2. `coach/judge.py` (per-part schema)
3. `coach/session.py`, `coach/selection.py`, `coach/picker.py`
4. `backend/v1/schemas.py`, `backend/v1/tasks.py`, `backend/v1/sessions.py`,
   `backend/admin_routes.py`, `coach/admin_tables.py`
5. `coach/seed_bank.py` (restructure catalog + versioned chains)
6. `coach/remediation.py`, `coach/task_decomposer.py`, `coach/solvability.py`,
   `coach/steps.py`, `coach/shares.py`
7. Frontend: `client.ts`, `ChatView.tsx`, `NewSeedForm.tsx`, store
8. Tests + `AGENTS.md`