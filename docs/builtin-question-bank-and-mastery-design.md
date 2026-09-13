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
3. **Stays hermetic and fast.** Seeds are fully pre-authored (no LLM or network
   at boot), inserted in a single batched transaction, and task
   creation/`initial_question` uses one combined LLM call.
4. **Uses a SQLite-legal schema.** A unique index (not an `ALTER TABLE`
   constraint) enforces one belief row per `(candidate, level, key)`, and
   belief lookups are updated so multiple rows never crash a scalar query.

---

## 1. Goals & scope

1. **Builtin question bank.** Ship a curated set of tasks with the app that
   covers "most of the important stuff in Machine Learning practice." Only
   topics whose mastery can be tested by **executing candidate code** are
   eligible; purely conceptual Q&A is out of scope. The catalog is kept **as
   small as possible**: each seed task is authored to exercise several tags at
   once, so a small set of tasks covers every family and every fine tag.
2. **Tag everything.** Every task — seed, user-created, or LLM-generated —
   carries a fine tag + family, so every attempt produces a mastery signal at
   both levels.
3. **Hierarchical mastery estimation.** Three Gaussian layers per candidate —
   `tag ← family ← global` — estimated with **order-invariant empirical-Bayes
   shrinkage computed at read time**. Sparse tags report ≈ family estimate;
   dense tags converge to the candidate's own evidence. No path-dependency.
4. **Scope-increasing selection.** The picker widens coverage into
   under-explored families/tags with **small, well-calibrated exploration
   bonuses** layered on top of the EIG engine, and LLM generation is
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
- The catalog is kept minimal (each seed covers multiple tags, §3.1), so the
  vocabulary must be small enough for a small seed set to cover every tag.

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

## 3. Builtin question bank

### 3.1 Catalog

A curated, static catalog lives in **`coach/seed_bank.py`** as
`SEED_CATALOG: list[SeedTask]`:

```
SeedTask = {
  "slug": "seed_softmax",            # stable id prefix
  "prompt": "Write a numerically stable softmax...",
  "scaffold": "def softmax(logits: list[float]) -> list[float]:\n    ...",
  "difficulty": 1-5,
  "max_score": 5,
  "hints": [...],                    # optional, ordered
  "tags": {"primary": "activation_normalization", "secondary": ["mlp", "loss_functions"]},
  "task_type": "implement",
  "context_notes": "…",              # REQUIRED, pre-authored, 2–4 sentences
}
```

**Minimal, multi-tag catalog.** Target size **~24–30 tasks** (roughly 2–3 per
family). Each seed task is authored as a **multi-tag exercise**: one primary tag
(feeds the estimator) plus 0–2 secondary tags (extend coverage). The catalog
covers **every family and every fine tag at least once** (counting primary +
secondary) without a dedicated task per tag. A tag covered only as a secondary
still counts as "covered" for selection and gap-filling; when the picker wants
to drill such a tag, tag-directed generation mints a task with it as primary
(§3.3).

Seed prompts are **code tasks** solvable with standard Python + NumPy in under
~30 lines. Illustrative examples (the full catalog is ~24–30):

| Seed task (code) | primary tag | secondary tags |
|---|---|---|
| Numerically stable softmax + log-softmax | `dl_arch.activation_normalization` | `training.loss_functions` |
| K-fold CV with stratification | `eval.cross_validation` | `data_etl.pandas_cleaning`, `stats_probability.bias_variance` |
| Linear regression with R² | `ml_classical.linear_regression` | `stats_probability.bias_variance`, `eval.regression_metrics` |
| K-Means (Lloyd's) + elbow check | `ml_classical.clustering_kmeans` | `data_etl.pandas_cleaning`, `eval.metrics_classification` |
| PCA via SVD + variance explained | `ml_classical.dimensionality_reduction` | `feature_eng.scaling_encoding`, `data_etl.pandas_cleaning` |
| Backprop for a 2-layer MLP | `training.backprop` | `dl_arch.mlp`, `optimization.gradient_descent_sgd` |
| Scaled dot-product attention head | `dl_arch.attention_transformer` | `llm_genai.kv_cache` |
| Retrieval + scoring over a small corpus | `llm_genai.rag_retrieval` | `data_etl.pandas_cleaning` |
| Incremental attention with KV cache | `llm_genai.kv_cache` | `dl_arch.attention_transformer` |
| Metrics + confusion matrix | `eval.metrics_classification` | `ml_classical.classification_logistic` |
| Bootstrap CI for a statistic | `stats_probability.bootstrap_ci` | `data_etl.missing_outliers` |
| Class-weighted oversampling | `feature_eng.imbalanced_classes` | `ml_classical.classification_logistic` |
| z-score anomaly detector | `data_etl.missing_outliers` | `stats_probability.distributions` |
| Cosine decay LR schedule | `training.lr_scheduling` | `optimization.gradient_descent_sgd` |
| Thread-safe bounded queue | `python.data_structures` | `python.generators_iterators` |
| int8 quantize + dequant | `llm_genai.quantization` | `mlops_serving.deployment_serving` |
| PSI / KS drift score | `mlops_serving.monitoring_drift` | `eval.metrics_classification` |
| Functional-style ETL pipeline | `python.functional` | `data_etl.pandas_cleaning`, `data_etl.joins_merges` |

Every catalog entry ships a **pre-authored `context_notes` string** (no LLM
call at seed time, §3.2).

Authoring rule enforced by review, not code: **every seed must be
self-contained, deterministic, and gradeable by the existing code judge.**

### 3.2 Seeding (idempotent, hermetic, fast)

- `seed_question_bank()` in `coach/tasks.py`, invoked from `create_schema()`
  (startup) so it self-heals on fresh databases and in tests.
- **No network and no model calls.** All `context_notes` are pre-authored in
  the catalog. Seeding is a single batched transaction:
  `INSERT OR IGNORE INTO tasks (...) VALUES (...), …` — one commit for the whole
  catalog, not one transaction per task.
- `task_id = f"seed_{slug}"`, `owner="system"`, `source="seed"`,
  `is_public=1`. `INSERT OR IGNORE` is keyed on the primary key, so re-runs are
  no-ops.
- **A seed row edited by a human is never overwritten** — `INSERT OR IGNORE`
  only inserts when the id is absent. To ship a content fix, bump the slug
  (e.g. `seed_softmax_rev2`) so the corrected task is added alongside the
  stale-but-human-edited one; the old row can be deprecated in a later cleanup.
- Seeds are already visible to every candidate through `list_visible_tasks`
  (`owner='system'` + `is_public=1`) — no visibility code change needed.

### 3.3 Coverage report & gap-filling

- `coverage_report()` returns, per family and per tag: seed count (a tag/family
  counts as covered if it appears as **primary or secondary** on any seed), plus
  per-candidate asked counts (from `task_attempts` joined on task tags). Used by
  the admin UI and by the generator.
- **Tag-directed generation** (the "gradually new tasks are generated" path):
  - `generate_seed_task_for_tag(tag, difficulty) -> SeedTask` in
    `coach/task_decomposer.py` — one Gemini call (reusing
    `_FOLLOWUP_SCHEMA`-style JSON) returning a self-contained code task for that
    exact tag, with the tag pre-attached as primary.
  - A CLI/admin action `python -m coach.seed_bank --fill-gaps [--limit N]`
    mints tasks for tags with **zero seed coverage** (or lowest coverage),
    persisted as `source="seed_llm"`, `is_public=1`.
  - Generated seeds are still judged normally; a human can PATCH them (owner is
    system → admin only), and any human edit disables future auto-overwrites
    via the idempotent insert.

### 3.4 Per-session generated tasks

Generated remediation drills/challenges inherit the root task's tags (see §6);
`plan_challenge` gains `prefer_family`/`prefer_tag` arguments so open-ended
tasks expand scope. All generated tasks are `create_task`-persisted (already
true) — now with tags, so re-asked tasks keep feeding the right beliefs.

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
   now — seeds, user tasks via the combined LLM call in §6, generated tasks via
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
- Seeds ship pre-tagged; `--fill-gaps` generation pre-attaches the target tag.
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
  Task bubbles show tag chips; the admin task list adds a tag column and a
  coverage-report view.

---

## 9. Files touched

**New**
- `coach/seed_bank.py` — `SEED_CATALOG` (pre-authored `context_notes`) +
  `seed_question_bank()` + `coverage_report()` + `--fill-gaps` CLI.
- `coach/taxonomy.py` — vocabulary (9 families / 36 tags), alias map,
  validation/lookup.
- `coach/area_score.py` — per-level own-statistics updates + read-time
  shrinkage fold (§4.1) + read helpers.
- `docs/builtin-question-bank-and-mastery-design-v3.md` — this doc.

**Modified**
- `coach/db.py` — `tags_json`/`task_type` columns; `level`/`key` on beliefs;
  unique index; seed hook into `create_schema`; fix scalar belief lookups.
- `coach/tasks.py` — tags in model/dict/CRUD, batched seed insert,
  `save_family_belief`/`save_tag_belief`/`get_area_beliefs`.
- `coach/session.py` — `family_states`/`tag_states` serialize/restore;
  `task_view` emits tags/task_type.
- `coach/task_decomposer.py` — combined `describe_task`+`categorize_task`,
  `generate_seed_task_for_tag`, tag inheritance in `_build`,
  `prefer_family`/`prefer_tag` in `generate_challenge_task`.
- `coach/picker.py` — exploration terms + soft breadth penalty.
- `coach/remediation.py` — least-covered family/tag selection in
  `plan_challenge`.
- `backend/v1/schemas.py`, `backend/v1/tasks.py`, `backend/v1/sessions.py`.
- `frontend/.../LearnerProgressView.tsx` (family bars + tag chips), task tag
  chips, admin tag column + coverage report view.

---

## 10. Tests & verification

Backend (`pytest`):
- Seed bank: idempotent re-seed; admin-edited seeds not overwritten; batched
  single-transaction insert; **catalog coverage** — every family and every fine
  tag is covered by at least one seed task (primary or secondary);
  coverage_report counts; `--fill-gaps` only touches zero-coverage tags;
  **seeding runs with no API key and no network**.
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
- Round-trip: tags persist seed → user → generated through create/PATCH/list;
  `task_view` emits tags/task_type.

Frontend: `npm test`, `npx tsc -b`, `npm run lint`.

---

## 11. Implementation sequence

1. `coach/taxonomy.py` + validation tests.
2. Schema/migration: `tags_json` (default `'{}'`), `task_type`,
   `level`/`key` + unique index; fix scalar lookups.
3. `coach/area_score.py` per-level updates + read-time fold + tests
   (incl. order-invariance).
4. `coach/tasks.py` + `coach/session.py` persistence/serialization + seed hook.
5. `coach/seed_bank.py`: catalog (families-first, ~24–30 multi-tag tasks, all
   pre-authored), batched seeding, coverage report, `--fill-gaps`; tests.
6. Combined `categorize_task`/`describe_task` + `generate_seed_task_for_tag` +
   API wiring.
7. Picker exploration + soft breadth penalty + `prefer_tag` challenge
   targeting; tests.
8. Frontend: progress per-family bars + tag chips + admin coverage view.
9. Full test/lint/typecheck pass; update `AGENTS.md` notes.