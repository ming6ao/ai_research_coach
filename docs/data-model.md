# Data Model

Status: **Current** (matches `coach/db.py`, `coach/steps.py`, `coach/tasks.py`,
`backend/dependencies.py`)
Persistence: single SQLite file `data/coach.db` (gitignored, created on first run, WAL mode)

## Overview

Nine tables split between two access layers that share one file:

| Layer | Module | Tables |
|-------|--------|--------|
| Raw `sqlite3` (hand-written SQL) | `coach/db.py` (`sqlite_conn`), `backend/auth.py`, `backend/dependencies.py`, `backend/google_auth.py` | `users`, `auth_tokens`, `active_sessions`, `oauth_states` |
| SQLAlchemy ORM (`coach.db.Base`) | `coach/tasks.py`, `coach/steps.py`, `coach/explanations.py`, `coach/custom_skills.py` | `tasks`, `session_steps`, `user_skill_beliefs`, `explanations`, `custom_skills` |

`create_schema()` (called at startup and lazily from the task/step CRUD paths) is
idempotent: it creates all tables, drops removed knowledge-graph/learner tables,
drops removed columns, migrates legacy beliefs, backfills `session_steps`
from legacy JSON blobs, and merges the active DB's `custom_skills` rows into the
live taxonomy. It never writes tasks — the `tasks` table is the source
of truth and is populated through the API. All timestamps are stored as naive
UTC.

## Tables

### `users`
Identity for signed-in users (Google-only auth, keyed by email).

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT | PK |
| `email` | TEXT | NOT NULL, UNIQUE |
| `password_hash` | TEXT | NOT NULL (unused by the current Google-only flow) |
| `display_name` | TEXT | nullable |
| `created_at` | TEXT | NOT NULL |

### `auth_tokens`
Session tokens (`Authorization: Bearer` header or HttpOnly `ai_coach_token` cookie).

| Column | Type | Notes |
|--------|------|-------|
| `token` | TEXT | PK |
| `user_id` | TEXT | NOT NULL, FK → `users.id` |
| `created_at` | TEXT | NOT NULL |
| `expires_at` | TEXT | NOT NULL |

Index: `idx_auth_tokens_user (user_id)`.

### `oauth_states`
Single-use Google OAuth `state` values (DB-backed so the flow works across workers).

| Column | Type | Notes |
|--------|------|-------|
| `state` | TEXT | PK |
| `expires_at` | TEXT | NOT NULL (expired rows swept on use) |

Index: `idx_oauth_states_expiry (expires_at)`.

### `active_sessions`
Episode header. One row per session; the compact live state is serialized in
`session_json`. **This table doubles as the history store**: rows are never
deleted on finish, so past sessions are just `active_sessions` rows for the same
`candidate`. The trajectory itself (per-step transitions) lives in
`session_steps`.

| Column | Type | Notes |
|--------|------|-------|
| `session_id` | TEXT | PK (12 hex chars) |
| `candidate` | TEXT | NOT NULL — learner identity (see Candidate identity) |
| `status` | TEXT | NOT NULL — always `active` in practice; "done" is derived at read time (`pick_next_task` returns `None`) |
| `session_json` | TEXT | NOT NULL — compact live state (schema below), `{}` on create |
| `meta_json` | TEXT | NOT NULL default `{}` — reserved; currently always empty |
| `updated_at` | TEXT | NOT NULL (ISO timestamp, bumped on every submit) |

Index: `idx_active_sessions_candidate (candidate)`.

#### `session_json` — compact live state

Written by `SessionState.save` on create and after every submit. It holds the
episode's *bookkeeping* only — per-step data (results, coaching, belief
transitions) lives in `session_steps`:

```json
{
  "session": {
    "candidate": "user@example.com | guest-<id>",
    "tasks": [ Task, ... ],
    "index": 3,
    "ability": { "score": 0.62, "variance": 0.09, "confidence": 0.66, "questions_answered": 3, "evidence": [...] },
    "asked_task_ids": ["task_ab12cd34ef"],
    "generated_task_ids": ["task_ab12cd34ef"],
    "task_progress": { "task_ab12cd34ef": 1 },
    "phase_attempts": {},
    "submission_index": 3
  }
}
```

- `Task` — the task dict (see `task_to_dict`, `coach/tasks.py`): `id`,
  `prompt` (derived from the first step), `difficulty` (1–5), `max_score`,
  `parts` (one or more steps:
  `[{key, prompt, tags, max_score, difficulty, scaffold, pass_score?}]`),
  `context_notes`, `tags` (`{primary, secondary[]}`), `task_type`, `language`,
  `source`, `is_public`, `owner`, plus optional `parent_task_id`,
  `target_text`. Generated follow-ups/challenges add in-session-only keys:
  `generated: true`, `generated_kind` (`remediate|escalate|pivot|challenge`),
  `root_task_id`, `root_difficulty`.
- `ability` — Gaussian `SkillState` (`coach/session.py`): `score` (posterior
  mean), `variance`, `confidence`, `questions_answered`, `evidence[]`.
- `index` — number of tasks completed so far; used as
  `remaining = len(tasks) - index`.
- `task_progress` / `phase_attempts` / `submission_index` — step bookkeeping:
  steps completed per task, a legacy per-step attempt counter (delivery now
  always advances, so `phase_attempts` is retained for backward compatibility
  and is no longer written), and the monotonic `session_steps.step_index`
  counter.

Past sessions are listed per candidate via `GET /api/v1/me/sessions`
(`store.list_by_candidate`, newest first); `done` is derived at read time by
re-running `pick_next_task` (returns `None` once the bank is exhausted).
Cross-session ability/mastery aggregates are *not* stored here — they live in
`user_skill_beliefs` (raw steps in `session_steps`), keyed by the same
`candidate`.

### `tasks`
The question bank, authored directly in the DB via `POST /api/v1/tasks` or the
curator UI. Each task
carries tags (1 primary leaf skill + 0–2 secondary) and a `task_type`.
Delivery is always **step-by-step**: `parts` are shown one at a time
(every submission advances to the next step regardless of the score, code
carried forward). Every task has at least one part; a
single-step question is a one-part task (there is no partless request).
Task-level `difficulty`/`max_score` and `prompt` are all derived from the steps:
`prompt` is always the first step's prompt, never authored separately. The old
`prompt` column was dropped; `create_schema()` wraps any legacy partless row
into a single part before removing it.

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(64) | PK (`task_<hex>`) |
| `owner` | VARCHAR(255) | NOT NULL — candidate email or guest id (every task has a user owner) |
| ~~`prompt`~~ | — | **dropped** — the task prompt is derived at read time from the first step (`_task_prompt`) |
| `scaffold` | TEXT | nullable — legacy/single-step starter code (step scaffolds live in `parts_json`) |
| `difficulty` | INTEGER | NOT NULL, 1–5 |
| `max_score` | INTEGER | NOT NULL, default 5 |
| `parts_json` | TEXT | NOT NULL — step list `[{key, prompt, tags, max_score, difficulty, scaffold, pass_score?}]` (per-step `scaffold` is required) |
| `context_notes` | TEXT | 2–4 plain-English sentences, generated once at creation |
| `tags_json` | TEXT | `{"primary": <leaf skill>, "secondary": [<leaf skill>…]}` (closed vocabulary from `coach/taxonomy.py`) |
| `task_type` | TEXT | `implement | apply | debug | design | analyze` |
| `language` | VARCHAR(32) | NOT NULL, default `python` — Monaco editor language id |
| `source` | VARCHAR(32) | NOT NULL — `user`/`generated` (`generated` is legacy: adaptive drills/challenges are session-only and no longer written here) |
| `parent_task_id` | VARCHAR(64) | nullable — legacy root task for generated follow-ups |
| `target_text` | TEXT | nullable — legacy judge's misconception/gap text for generated drills |
| `delivery` | VARCHAR(16) | NOT NULL — always `'phased'`; legacy `'block'` rows are normalized by `python -m coach.migrate delivery --apply` |
| `is_public` | INTEGER | NOT NULL — visibility flag (public rows are visible to everyone; guests create public rows, signed-in default private) |
| `created_at` | DATETIME | NOT NULL |

Index: `ix_tasks_owner (owner)`.

Visibility (`list_visible_tasks`): a candidate sees their own rows and every
`is_public=1` row (there are no system-owned rows). LLM-generated adaptive
drills/challenges are **session-only** (stored in `active_sessions.session_json`
via `generated_task_ids`, never in this table), so `pick_next_task`'s read paths
(`GET /sessions/{id}`, `_replay_response`) pass `allow_generation=False` and
never mint a row; `POST /admin/reset` drops any legacy `source='generated'`
rows along with the sessions.

### `session_steps`
RL-shaped per-step log — one row per scored answer (an episode transition
`s_t → a_t → r_t → s_{t+1}`). Supersedes the legacy `task_attempts` table and
the `feedback_json` blob; review reads from here and a future episode
export is a plain `SELECT ... ORDER BY session_id, step_index`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(36) | PK (uuid) |
| `session_id` | VARCHAR(64) | NOT NULL → `active_sessions.session_id` (deleted on session delete) |
| `candidate` | VARCHAR(255) | NOT NULL — denormalized for coverage/admin aggregation |
| `step_index` | INTEGER | NOT NULL — 0-based position in the episode |
| `task_id` | VARCHAR(64) | nullable → `tasks.id` (deleted on task delete) |
| `task_snapshot_json` | TEXT | NOT NULL — immutable observation (task as-asked) |
| `role` | VARCHAR(32) | NOT NULL — `bank \| remediate \| escalate \| pivot \| challenge` (legacy rows may carry `redo`) |
| `user_answer` | TEXT | NOT NULL — the action |
| `score` / `max_score` / `fraction` | FLOAT | judge output |
| `reward` | FLOAT | NOT NULL — effective fraction ∈ [0, 1] |
| `state_before_json` | TEXT | NOT NULL — `s_t` (`{global, nodes}` belief snapshot) |
| `state_after_json` | TEXT | NOT NULL — `s_{t+1}` |
| `result_json` | TEXT | NOT NULL — judge result (rationale) |
| `coaching_json` | TEXT | NOT NULL — coach content (misconception, steps) |
| `created_at` | DATETIME | NOT NULL |

Indexes: `uq_session_steps (session_id, step_index)` UNIQUE,
`ix_session_steps_task (task_id)`, `ix_session_steps_candidate (candidate)`.

RL mapping: episode = the `active_sessions` row + its steps; timestep =
`step_index` (0-based); observation = `task_snapshot_json`; state `s_t` =
`state_before_json` / `s_{t+1}` = `state_after_json` (global + per-node Gaussian
beliefs); action = `user_answer`; reward = `reward` (effective fraction ∈ [0,1]);
done = derived at read time (`pick_next_task` returns `None`).

### `user_skill_beliefs`
Persistent Gaussian beliefs — the mastery model. One row per
`(candidate, level, key)`, enforced by a unique index:

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(36) | PK (uuid) |
| `candidate` | VARCHAR(255) | NOT NULL |
| `level` | TEXT | NOT NULL — `global | domain | area | skill` |
| `key` | TEXT | NOT NULL — `overall`, or a canonical taxonomy node id |
| `mean` | FLOAT | NOT NULL — Gaussian mean, default 0.5 |
| `variance` | FLOAT | NOT NULL — Gaussian variance, default 0.1225 |
| `questions_answered` | INTEGER | NOT NULL — evidence count at this level |
| `updated_at` | DATETIME | NOT NULL |

Indexes: `ix_skill_beliefs_candidate (candidate)`,
`uq_user_skill_beliefs (candidate, level, key)` UNIQUE.

Only the task's **primary leaf skill** feeds the estimator: one answer updates
exactly one skill row, plus its area and domain rows, plus the global row.
Reported mastery is folded at read time from own evidence toward the parent
(empirical-Bayes shrinkage, `eta=2.0`).

### `custom_skills`
Curator-added **leaf skills** layered on the built-in `coach/taxonomy.py`
vocabulary (domains and areas stay fixed in code). Registered through
`POST /api/v1/taxonomy/skills`, they are merged into the live
`TAXONOMY`/`LEAF_NODES`/`NODE_*` maps by `coach/custom_skills.py` at startup
(and on demand), so tagging, beliefs, mastery folding, and the picker treat
them exactly like built-in leaves. `POST /admin/reset?wipe_tasks=true` drops
them along with the bank; a plain reset preserves them.

| Column | Type | Notes |
|--------|------|-------|
| `skill` | VARCHAR(64) | PK — canonical skill id (lowercase, underscores) |
| `area` | VARCHAR(64) | NOT NULL — an existing area id |
| `created_by` | VARCHAR(255) | nullable — curator email |
| `created_at` | DATETIME | NOT NULL |

### `explanations`
Selection-driven explanations ("Explain this"): one row per highlighted
passage the learner asked about (`coach/explanations.py`, routes in
`backend/v1/explanations.py`). These are **not** scored transitions — they never
enter `session_steps` and never update `user_skill_beliefs`. They back the
right-hand explanation panel (restored on resume/review), cache identical
requests per session (`request_hash`), and record follow-up threads
(`parent_id`). Deleted with their session by `SessionState.delete`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(36) | PK (uuid) |
| `session_id` | VARCHAR(64) | NOT NULL → `active_sessions.session_id` |
| `candidate` | VARCHAR(255) | NOT NULL — denormalized for curation/analytics |
| `task_id` | VARCHAR(64) | nullable — the task the passage came from |
| `step_key` | VARCHAR(64) | nullable — the active step's key |
| `phase_index` | INTEGER | nullable — 0-based step position |
| `source_kind` | VARCHAR(16) | `question \| coaching \| context \| code \| other` |
| `selected_text` | TEXT | NOT NULL — the highlighted passage (≤4000 chars) |
| `context_text` | TEXT | NOT NULL default `''` — enclosing paragraph (≤800) |
| `question` | TEXT | nullable — follow-up question |
| `parent_id` | VARCHAR(36) | nullable — self-reference for follow-up threads |
| `request_hash` | VARCHAR(64) | NOT NULL — sha256 for per-session dedup |
| `title` | TEXT | NOT NULL default `''` — short concept title |
| `explanation` | TEXT | NOT NULL default `''` — markdown (KaTeX + code) |
| `related_terms_json` | TEXT | NOT NULL default `'[]'` |
| `model` | VARCHAR(64) | NOT NULL default `''` |
| `status` | VARCHAR(16) | NOT NULL — `ok` (only successes are stored) |
| `created_at` | DATETIME | NOT NULL |

Indexes: `ix_explanations_session (session_id)`,
`ix_explanations_candidate (candidate)`, `ix_explanations_task (task_id)`,
`ix_explanations_hash (session_id, request_hash)`.

## Candidate identity

The learner key used by `candidate` columns is resolved by
`backend/dependencies.py:resolve_candidate`:

- Signed-in user → their `users.email`.
- Guest → `guest-<X-Guest-Id>` where the header comes from a stable per-browser
  `localStorage` value (regex-guarded `[A-Za-z0-9_-]{8,64}`); a missing/malformed
  header falls back to a fresh ephemeral `guest-<8 hex>` id.

## Schema lifecycle / migrations

`coach/db.py:create_schema()` runs idempotently (guarded per DB file):

1. `Base.metadata.create_all` — creates `tasks`, `session_steps`, `user_skill_beliefs`, `explanations`.
2. Drops removed knowledge-graph/learner tables (`knowledge_nodes`,
   `knowledge_edges`, `learners`, `learner_knowledge_states`, `evidence`,
   `learner_misconceptions`, `learner_frontier`, `assessment_targets`,
   `assessment_tasks`), the superseded `task_attempts` table, the removed
   `trajectory_shares` table, and dropped task
   columns (`graph_json`, `target_node_id`, `target_node_slug`,
   `expected_time_min`, `skill`, `hints_json`, `cluster_id`, `followups_json`,
   `version_index`, `depends_on_task_id`, `version_root_id`).
3. Adds `context_notes`, `target_text`, `tags_json`, `task_type`, `language`,
   `parts_json`, `delivery` to `tasks` if absent, and `status` / `meta_json` to
   `active_sessions` if absent; drops retired `active_sessions` columns
   (`resumed_from_share`, `fork_of`) and `session_steps.inherited`.
4. `_migrate_skill_beliefs_to_ability` — adds `level`/`key` to
   `user_skill_beliefs`, collapses legacy per-skill rows to
   `('global', 'overall')` (most answered wins; per-node rows are rebuilt under
   the new hierarchy), drops the legacy `skill` column, dedupes
   `(candidate, level, key)`, and creates `uq_user_skill_beliefs`.
5. `_migrate_active_sessions` — drops the legacy `feedback_json` column **only
   after** every session has been backfilled (or has no legacy results); the
   column is kept while any session still needs replay.
6. `backfill_session_steps()` — deterministic replay of legacy
   `session_json`/`feedback_json` blobs into `session_steps` (per-step
   `state_before`/`state_after` reconstructed via the Bayesian belief update);
   idempotent and best-effort.

All migration steps are best-effort (exceptions swallowed so startup never breaks).