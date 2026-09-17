# Builtin ML Question Bank + Hierarchical Mastery Design

Status: **Proposed**
Owner: AI Research Coach

This design:

1. **Estimates mastery with order-invariant, read-time empirical-Bayes
   shrinkage.** Sparse tags report ≈ their family's estimate; dense tags
   converge to the candidate's own evidence; identical answers in any order
   produce identical beliefs.
2. **Keeps exploration a tiebreaker, not a replacement.** Exploration bonuses
   are calibrated so they never swamp the EIG engine, and the breadth guard is
   a soft penalty that cannot deadlock selection.
3. **Treats the database as the source of truth for tasks.** There is no
   code-embedded catalog; the `tasks` table is the question bank, populated
   through the API (`POST /api/v1/tasks`, curator UI, admin "Add question").
4. **Uses a SQLite-legal schema.** A unique index (not an `ALTER TABLE`
   constraint) enforces one belief row per `(candidate, level, key)`, and
   belief lookups are updated so multiple rows never crash a scalar query.

---

## 1. Goals & scope

1. **DB-managed question bank.** The `tasks` table is the only question bank —
   the database is the source of truth, not source code. Tasks are authored in
   the DB via `POST /api/v1/tasks`, the curator UI ("My questions"), or the
   admin "Add question" form (`POST /admin/seeds`); a fresh database starts
   with an empty bank until tasks are added. Only topics whose mastery can be
   tested by **executing candidate code** are eligible; purely conceptual Q&A is
   out of scope.
2. **Tag everything.** Every task — user-created, admin-authored, or
   LLM-generated — carries a fine tag + family, so every attempt produces a
   mastery signal at both levels.
3. **Hierarchical mastery estimation.** Three Gaussian layers per candidate —
   `tag ← family ← global` — estimated with **order-invariant empirical-Bayes
   shrinkage computed at read time**. Sparse tags report ≈ family estimate;
   dense tags converge to the candidate's own evidence. No path-dependency.
4. **Scope-increasing selection.** The picker widens coverage into
   under-explored families/tags with **small, well-calibrated exploration
   bonuses** layered on top of the EIG engine, and challenge generation is
   *tag-directed* so new tasks land on uncovered areas.

Non-goals: no knowledge graph; no new dependencies; no changes to the judge,
hints, remediation loop, or session lifecycle.

---

## 2. Vocabulary (code-gradable ML topics)

**9 families and 36 fine tags.** The vocabulary is deliberately limited to
topics that can be graded by executing candidate code — a conceptual question
(e.g. "explain the CAP theorem") is not in the catalog unless it can be posed
as a self-contained Python exercise.

Rationale for the size:

- A typical session is 5–12 questions. Fine tags must be coarse enough to
  accumulate evidence within a handful of sessions; a much finer vocabulary
  would leave most tag bars as pure priors.
- Tags are covered by whatever tasks exist in the bank (§3), so the vocabulary
  must be small enough for a practical task set to cover every tag.

| Family | Fine tags |
|---|---|
| `python` | `data_structures`, `functional`, `generators_iterators` |
| `data_etl` | `pandas_cleaning`, `joins_merges`, `missing_outliers` |
| `feature_eng` | `scaling_encoding`, `feature_construction`, `imbalanced_classes` |
| `ml_classical` | `linear_regression`, `classification_logistic`, `trees_ensembles`, `clustering_kmeans`, `dimensionality_reduction`, `knn_svm_naivebayes` |
| `stats_probability` | `bias_variance`, `distributions`, `hypothesis_pvalue`, `bayes_mle`, `bootstrap_ci` |
| `training` | `loss_functions`, `regularization`, `backprop`, `lr_scheduling`, `overfitting_underfitting` |
| `optimization` | `gradient_descent_sgd`, `optimizers_adam`, `hyperparameter_tuning` |
| `dl_arch` | `mlp`, `cnn`, `rnn_lstm`, `attention_transformer`, `activation_normalization` |
| `llm_genai` | `tokenization_bpe`, `pretraining_finetuning`, `rag_retrieval`, `quantization`, `kv_cache` |
| `eval` | `metrics_classification`, `regression_metrics`, `cross_validation`, `data_leakage_calibration` |
| `mlops_serving` | `deployment_serving`, `monitoring_drift`, `explainability`, `reproducibility_tracking` |

Notes on what was excluded and why:

- **No standalone `vision`, `generative_models`, `nlp`, or `sys_*` infra
  families.** Their canonical questions are conceptual and cannot be graded by
  executing a short Python function (e.g. Raft consensus, GPU batching, diffusion
  training). Gradeable content from those areas folds into the families above:
  `producer_consumer`/`threading_locks` → `python`; `attention`/`transformer` →
  `dl_arch`; `tokenization_bpe`, `kv_cache`, `quantization` → `llm_genai`.
- **One canonical tag per concept.** No duplicates or near-duplicates
  (e.g. a single `attention_transformer` tag rather than separate `attention`
  and `transformer_attention`; `bootstrap_ci` lives only under
  `stats_probability`).
- **No tag maps to more than one family** (single source of truth
  `TAG_TO_FAMILY`).

### Task tagging contract

- `tags: { primary: <fine tag>, secondary: [<fine tag>, …] }` — 1 primary,
  0–2 secondary; each maps to exactly one family.
- Closed vocabulary validated server-side (`coach/taxonomy.py` is the single
  source of truth: `FAMILIES`, `TAG_TO_FAMILY`, `ALIASES`, `validate`,
  `family_of`).
- **Only the primary tag feeds the belief system** (one answer updates exactly
  one tag + one family + the global estimate). Secondary tags contribute to
  coverage reporting and task diversity only — never to the estimator. This
  avoids double-counting one answer into multiple tags.
- Each task also carries `task_type` (`implement | apply | debug | design |
  analyze`). A "design" scenario is still implemented as a code task whose
  `scaffold` pins the key component, and is judged normally.

---

## 3. Question bank (database as source of truth)

### 3.1 The `tasks` table is the bank

There is **no code-embedded catalog**. All tasks live in the `tasks` table and
are authored through the API:

- `POST /api/v1/tasks` — any signed-in user creates a task (optional
  `initial_question` on `POST /api/v1/sessions` for one-off prompts).
- The curator UI ("My questions") — the same v1 API with a form + learner-view
  preview.
- The admin "Add question" form (`POST /admin/seeds`) — owner `system`,
  `source="seed_admin"`, `is_public=1`.

A fresh database starts with an empty bank; the admin/tasks rows are the
question set until more are added. `create_schema()` never writes tasks and
`reset_database()` preserves the task bank.

A task may be a **code block**: one task-level `scaffold` covering related
functions, with `parts: [{key, prompt, tags, max_score, difficulty}]` scored
per part by the judge. Tasks link into **version chains** via
`depends_on_task_id` / `version_root_id` (`version_index`); a successor
modifies the predecessor's code and is judged against its own criteria with the
predecessor's answer shown as `previous_code`.

### 3.2 Task shape & tagging

Every task carries `tags: {primary, secondary[]}` + `task_type`; every part
carries its own tags too. `context_notes` (2–4 plain-English sentences) is
generated once at creation by one combined LLM call
(`describe_and_categorize`), with a deterministic no-API-key fallback, and is
editable via `PATCH /api/v1/tasks/{id}`.

Authoring rule: every task must be self-contained, deterministic, and gradeable
by the existing code judge. No hints (`coach/hints.py` was removed).

### 3.3 Coverage & gap-filling

Coverage is whatever the DB currently contains — there is no separate seed
coverage report. Under-explored families/tags are reached at runtime: the
picker's exploration bonuses steer the bank branch, and when the bank has no
eligible task for an area the scope-widening challenge generates one
(`plan_challenge(prefer_tag=...)`, §5). The picker excludes non-root version
successors from the bank (successors only appear as follow-ups to their
predecessor).

### 3.4 Generated tasks

Remediation drills and scope-widening challenges are `create_task`-persisted
(`source="generated"`) and inherit the root task's tags (see §6);
`plan_challenge` gains `prefer_family`/`prefer_tag` arguments so open-ended
tasks expand scope. Re-asked tasks keep feeding the right beliefs.

---

## 4. Mastery signals — how every attempt feeds family & tag beliefs

### 4.1 Estimation design (order-invariant read-time shrinkage)

We store **sufficient statistics per level** and compute the reported estimate
at read time, so the same answers in any order produce the same beliefs.

Per candidate, for the global estimate, each family, and each fine tag, store:

- `mu`: the mean of the candidate's own (hint-adjusted) observations for that
  level.
- `variance`: the Bayesian posterior variance from a **neutral prior**
  `N(INITIAL_SCORE, INITIAL_VARIANCE)` updated only by observations *at that
  level* (tag observations update the tag's own statistics, family observations
  update the family's, and so on). No cross-level seeding.
- `questions_answered`: the count of observations at that level.

At **read time** (progress view, picker, coverage report) compute the shrunk
reporting estimate:

```
eta  = 2.0                      # shrinkage strength (tuned, see below)
w(x) = n_x / (n_x + eta)        # weight on the candidate's own evidence

reported_mu(level)  = w * mu_own + (1 - w) * parent_mu_shrunk
reported_var(level) = (w^2 * var_own + (1-w)^2 * parent_var_shrunk)
```

where the parent of a tag is its family's reported estimate and the parent of a
family is the global reported estimate. Consequently:

- An **unattempted tag** has `n=0 → w=0` and reports exactly its family's
  shrunk estimate — the UI never shows a blank bar or a raw neutral prior.
- A **sparse tag** (1–2 attempts) reports mostly its family's estimate, with
  honest, *not* artificially tiny, uncertainty.
- A **dense tag** (n ≫ η) converges to the candidate's own mean; the same
  answers in any order yield the same result (no path-dependency).
- The hierarchy (`tag → family → global`) is a pure read-time fold; there is no
  stateful coupling to keep in sync and no order-dependent initialization.

Why read-time shrinkage instead of stateful cross-level seeding:

- Stateful seeding is path-dependent: the posterior of an identical answer
  depends on *when* the tag is first seen, because it inherits whatever the
  family belief happens to be at that moment, and never moves again with later
  family evidence.
- Seeding a tag's variance from its family's *posterior* variance is variance
  starvation: a well-measured family (σ² ≈ 0.02) hands its untouched tag the
  same tiny variance, behaving as if the tag already had direct evidence, and
  making the first real observation barely move the belief.
- Read-time shrinkage reuses the existing `bayesian_update` for the per-level
  own-statistics and adds one small, order-invariant fold at read time.
- `eta = 2.0` is the single shrinkage knob; it is tuned once against synthetic
  sequences in tests.

### 4.2 Pipeline on `POST /api/v1/sessions/{id}/answers`

1. Resolve the task's primary tag `t` and family `f` (tasks always carry tags
   now — admin/user tasks via the combined LLM call in §6, generated tasks via
   inheritance).
2. Compute `y` (hint-adjusted effective score) as today
   (`coach/score.py:effective_score`).
3. **Tag update** (`coach/area_score.py`): `obs_var_t =
   measurement_variance(difficulty, mu_t_own)`; update the tag's *own*
   statistics with `bayesian_update(mu_t_own, var_t_own, y, obs_var_t)`;
   `questions_answered_t += 1`.
4. **Family update**: `obs_var_f = measurement_variance(difficulty, mu_f_own)`;
   update the family's own statistics; `questions_answered_f += 1`.
5. **Global update** (existing): `bayesian_update` on the global belief.

The reported estimate for any level is only materialized at read time via the
fold in §4.1, using the level's own statistics and its parent's reported
estimate. No observation is ever used twice inside a single level, and tag /
family / global each carry exactly their own evidence.

Persistence (`user_skill_beliefs` gains `level` + `key`, see §7):
`UNIQUE(candidate, level, key)` enforced by a **unique index** (not an
`ALTER TABLE` constraint — illegal in SQLite). Session runtime state:
`Session.family_states`, `Session.tag_states` serialized in
`to_dict`/`from_dict` so resume works, persisted alongside `save_skill_belief`.

Per-candidate coverage counters (`attempts_f`, `attempts_t`) are derived from
`family_states`/`tag_states.questions_answered` in-session, and from
`task_attempts` × task tags across sessions.

---

## 5. Scope-increasing selection

Utility in `coach/picker.py:_utility` becomes:

```
utility = EIG_global / time
        + lambda_family * explore(family_of(primary))
        + lambda_tag    * explore(primary_tag)
```

with `explore(x) = 1/(1 + attempts_x)`.

**Calibrated weights:**

| Constant | Value | Why |
|---|---|---|
| `lambda_family` | **0.004** | Must stay well below `EIG_global/time` (≈0.005–0.015) so exploration is a genuine tiebreaker, never a replacement. |
| `lambda_tag` | **0.001** | Tag-level coverage is secondary to family coverage. |
| `lambda_novel` | — (not used) | `explore(0) = 1` already awards full novelty; a separate novelty bonus would double-count it. |

With these weights, an unvisited family adds at most
`0.004·1 + 0.001·1 = 0.005` — a third of the EIG term on question 1 and
comparable later — so EIG remains the primary signal and difficulty / ability
still shape selection. Constants are unit-consistent with `EIG_global/time`.

Guards & interactions:

- **Breadth guard (soft).** Instead of hard-excluding the previous family
  (which could deadlock `next_task` → `None` and wrongly fall through to LLM
  challenge generation when only same-family tasks remained), apply a **penalty
  of `-0.010`** to a candidate task whose primary family equals the previously
  asked task's family. This breaks streaks without ever removing the last
  viable bank task.
- **Bank fallback:** when the bank has no eligible task for the current
  exploration target (e.g. a tag is fully exhausted), fall through to
  tag-directed generation for the least-covered family/tag via
  `plan_challenge(prefer_tag=...)`, so scope keeps widening even when the bank
  is drained for that area.
- `coach/selection.py` precedence is unchanged (pending generated →
  judge-driven follow-up → bank picker → challenge). Exploration reshapes only
  the bank-picker branch.
- `GET /api/v1/tasks?tag=<fine tag|family>` filter for admin/curation.

---

## 6. Tag assignment

- `coach/task_decomposer.py:categorize_task(prompt) -> {primary, secondary[]}`
  — Gemini call constrained to the vocabulary; deterministic fallback
  `{primary: "python", secondary: []}` when no API key.
- **Combined call.** Context-notes generation and tag categorization are a
  **single structured Gemini call** returning
  `{context_notes, primary_tag, secondary_tag}`. This keeps task-creation /
  `initial_question` latency at one LLM round-trip instead of two sequential
  ones. Wired into `_describe_context` (`backend/v1/sessions.py`) so `POST
  /api/v1/tasks` and session `initial_question` creation are auto-tagged.
- `TaskCreateRequest` / `TaskPatchRequest` accept optional `tags`; explicit
  tags override LLM output; `PATCH` validates against the vocabulary (422 on
  unknown).
- Generated remediation tasks inherit the root task's tags (`_build` in
  `coach/task_decomposer.py`); `generate_challenge_task` gains
  `prefer_family`/`prefer_tag`.

---

## 7. Data model & migration

- `tasks` gains `tags_json TEXT DEFAULT '{}'` — the default must be a JSON
  **object** `{"primary": "python", "secondary": []}`; a JSON-array default
  (`'[]'`) would make `json.loads` return a `list` and crash `.get()` on
  untagged rows — and `task_type TEXT DEFAULT 'implement'`; both added
  idempotently in `coach/db.py:create_schema` (same pattern as `context_notes`).
- `user_skill_beliefs` gains `level TEXT` and `key TEXT`:
  - `level` in `('global'|'family'|'tag')`, `key` = `'overall'` | family | tag.
  - `UNIQUE(candidate, level, key)` is enforced with
    `CREATE UNIQUE INDEX IF NOT EXISTS uq_user_skill_beliefs ON
    user_skill_beliefs (candidate, level, key)` — SQLite cannot add a UNIQUE
    constraint via `ALTER TABLE`.
  - Existing single rows per candidate migrate to `('global','overall')`.
    Legacy junk `skill` rows still collapse; any legacy skill name matching a
    known family is kept as `('family', <name>)`.
  - **All legacy scalar lookups must be updated** to filter on
    `level='global'` (e.g. `coach/tasks.py:get_skill_belief` currently uses
    `session.scalar(...)` with only `candidate == ...`; once multiple rows
    exist per candidate this raises `sqlalchemy.exc.MultipleResultsFound`).
- `task_to_dict` / `create_task` / `update_task` / `list_tasks_for_admin`
  round-trip tags and task_type.

---

## 8. API, serialization & frontend contract

- `task_view` (`coach/session.py`) must be extended to emit `tags` and
  `task_type`; it currently constructs a whitelist and would otherwise hide the
  new fields from the client.
- `POST /api/v1/sessions/{id}/answers` and `/completion` responses gain a
  `mastery` block:
  ```
  mastery: {
    global:   {score, confidence, questions_answered},
    families: {<family>: {score, confidence, questions_answered}},
    tags:     {<tag>:    {score, confidence, questions_answered}},
  }
  ```
  Scores here are the **read-time shrunk** estimates from §4.1.
  `ability_update` keeps the legacy `{new_score, new_confidence, hints_used}`
  shape so the existing frontend store contract (`SubmitResponse` /
  `AbilityUpdate` in `frontend/src/api/client.ts`) stays valid.
- `LearnerProgressView.tsx` renders per-family bars + tag chips from `mastery`.
  Task bubbles show tag chips; the admin task list adds a tag column.

---

## 9. Files touched

**New**
- `coach/taxonomy.py` — vocabulary (11 families / 46 tags), alias map,
  validation/lookup.
- `coach/area_score.py` — per-level own-statistics updates + read-time
  shrinkage fold (§4.1) + read helpers.
- `docs/builtin-question-bank-and-mastery-design-v3.md` — this doc.

**Modified**
- `coach/db.py` — `tags_json`/`task_type`/`parts_json`/version columns;
  `level`/`key` on beliefs; unique index; fix scalar belief lookups.
- `coach/tasks.py` — tags in model/dict/CRUD,
  `save_family_belief`/`save_tag_belief`/`get_area_beliefs`.
- `coach/session.py` — `family_states`/`tag_states` serialize/restore;
  `task_view` emits tags/task_type.
- `coach/task_decomposer.py` — combined `describe_task`+`categorize_task`,
  tag inheritance in `_build`, `prefer_family`/`prefer_tag` in
  `generate_challenge_task`.
- `coach/picker.py` — exploration terms + soft breadth penalty.
- `coach/remediation.py` — least-covered family/tag selection in
  `plan_challenge`.
- `backend/v1/schemas.py`, `backend/v1/tasks.py`, `backend/v1/sessions.py`.
- `frontend/.../LearnerProgressView.tsx` (family bars + tag chips), task tag
  chips, admin tag column.

**Removed**
- `coach/seed_bank.py` — the code-embedded catalog (`SEED_CATALOG`),
  `seed_question_bank()`, `coverage_report()`, and the `--fill-gaps`/`--reset`
  CLI. Tasks are DB-managed now.

---

## 10. Tests & verification

Backend (`pytest`):
- Categorization: no-key fallback; combined-call shape; unknown tag rejected on
  create/PATCH.
- Hierarchy: **order-invariance** (shuffle the same answer sequence → identical
  reported beliefs); sparse tag ≈ family estimate; dense tag ≈ own mean;
  unattempted tag ≈ family estimate (not blank); only primary tag updates
  beliefs; `eta` tuning sanity on synthetic sequences.
- Picker: exploration is a tiebreaker, not a dominator (EIG term dominates for
  a novel family); soft breadth guard never returns `None` when a same-family
  task is the only option; utility identical to today when all bonuses are 0
  (regression).
- Migration: existing rows → `global/overall`; junk collapse; known-family rows
  survive; unique index present; scalar `get_skill_belief` returns the global
  row without `MultipleResultsFound`.
- Round-trip: tags persist user → admin → generated through create/PATCH/list;
  `task_view` emits tags/task_type.
- Reset: `reset_database()` wipes activity but preserves the task bank +
  auth.

Frontend: `npm test`, `npx tsc -b`, `npm run lint`.

---

## 11. Implementation sequence

1. `coach/taxonomy.py` + validation tests.
2. Schema/migration: `tags_json` (default `'{}'`), `task_type`,
   `level`/`key` + unique index; fix scalar lookups.
3. `coach/area_score.py` per-level updates + read-time fold + tests
   (incl. order-invariance).
4. `coach/tasks.py` + `coach/session.py` persistence/serialization.
5. Remove the code-embedded catalog (`coach/seed_bank.py`): the `tasks` table
   becomes the source of truth; `create_schema()` stops writing tasks and
   `reset_database()` preserves them.
6. Combined `categorize_task`/`describe_task` + API wiring.
7. Picker exploration + soft breadth penalty + `prefer_tag` challenge
   targeting; tests.
8. Frontend: progress per-family bars + tag chips + admin task list.
9. Full test/lint/typecheck pass; update `AGENTS.md` notes.