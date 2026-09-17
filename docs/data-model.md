# Data Model

Status: **Current** (matches `coach/db.py`, `coach/steps.py`, `coach/tasks.py`,
`backend/dependencies.py`)
Persistence: single SQLite file `data/coach.db` (gitignored, created on first run, WAL mode)

> The anonymous Copy-on-Write trajectory sharing/resume design and RL-shaped
> episode storage live in [`docs/collaboration-design.md`](./collaboration-design.md).

## Overview

Eight tables split between two access layers that share one file:

| Layer | Module | Tables |
|-------|--------|--------|
| Raw `sqlite3` (hand-written SQL) | `coach/db.py` (`sqlite_conn`), `coach/shares.py`, `backend/auth.py`, `backend/dependencies.py`, `backend/google_auth.py` | `users`, `auth_tokens`, `active_sessions`, `oauth_states`, `trajectory_shares` |
| SQLAlchemy ORM (`coach.db.Base`) | `coach/tasks.py`, `coach/steps.py` | `tasks`, `session_steps`, `user_skill_beliefs` |

`create_schema()` (called at startup and lazily from the task/step CRUD paths) is
idempotent: it creates all tables, drops removed knowledge-graph/learner tables,
drops removed columns, migrates legacy beliefs, and backfills `session_steps`
from legacy JSON blobs. It never writes tasks — the `tasks` table is the source
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
| `status` | TEXT | NOT NULL — `active \| done` |
| `session_json` | TEXT | NOT NULL — compact live state (schema below), `{}` on create |
| `resumed_from_share` | TEXT | nullable — share token while the prefix is still a CoW reference (cleared on first write) |
| `fork_of` | TEXT | nullable — internal trajectory lineage (source session id, never surfaced) |
| `meta_json` | TEXT | NOT NULL default `{}` — `{node, initial_question, eval_model}` |
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
    "generated_task_ids": ["task_ab12cd34ef"]
  }
}
```

- `Task` — the task dict (see `task_to_dict`, `coach/tasks.py`): `id`, `prompt`,
  `difficulty` (1–5), `max_score`, `parts` (`[{key, prompt, tags, max_score,
  difficulty}]`, empty for a single-question task), `context_notes`, `tags`
  (`{primary, secondary[]}`), `task_type`, `source`, `is_public`, `owner`, plus
  optional `scaffold`, `parent_task_id`, `target_text`. Generated follow-ups/
  challenges add in-session-only keys: `generated: true`, `generated_kind`
  (`remediate|escalate|pivot|challenge`), `root_task_id`, `root_difficulty`.
- `ability` — Gaussian `SkillState` (`coach/session.py`): `score` (posterior
  mean), `variance`, `confidence`, `questions_answered`, `evidence[]`.
- `index` — number of tasks submitted so far; incremented per answer and used as
  `remaining = len(tasks) - index`.

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
(pass-gated, code carried forward); a partless task is one implicit step.
Task-level `difficulty`/`max_score` are derived from the steps when omitted.

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(64) | PK (`task_<hex>`) |
| `owner` | VARCHAR(255) | NOT NULL — candidate email or guest id (every task has a user owner) |
| `prompt` | TEXT | NOT NULL |
| `scaffold` | TEXT | nullable — legacy/single-step starter code (step scaffolds live in `parts_json`) |
| `difficulty` | INTEGER | NOT NULL, 1–5 |
| `max_score` | INTEGER | NOT NULL, default 5 |
| `parts_json` | TEXT | NOT NULL — step list `[{key, prompt, tags, max_score, difficulty, pass_score?, scaffold?}]` |
| `context_notes` | TEXT | 2–4 plain-English sentences, generated once at creation |
| `tags_json` | TEXT | `{"primary": <leaf skill>, "secondary": [<leaf skill>…]}` (closed vocabulary from `coach/taxonomy.py`) |
| `task_type` | TEXT | `implement | apply | debug | design | analyze` |
| `source` | VARCHAR(32) | NOT NULL — `user`/`generated` |
| `parent_task_id` | VARCHAR(64) | nullable — root task for generated follow-ups |
| `target_text` | TEXT | nullable — judge's misconception/gap text for generated drills |
| `delivery` | VARCHAR(16) | NOT NULL — always `'phased'`; legacy `'block'` rows are normalized by `python -m coach.migrate delivery --apply` |
| `is_public` | INTEGER | NOT NULL — visibility flag (public rows are visible to everyone; guests create public rows, signed-in default private) |
| `created_at` | DATETIME | NOT NULL |

Index: `ix_tasks_owner (owner)`.

Visibility (`list_visible_tasks`): a candidate sees `owner='system'` + `is_public=1`
rows, their own rows, and any `is_public=1` row.

### `session_steps`
RL-shaped per-step log — one row per scored answer (an episode transition
`s_t → a_t → r_t → s_{t+1}`). Supersedes the legacy `task_attempts` table and
the `feedback_json` blob; resume/review reads from here and a future episode
export is a plain `SELECT ... ORDER BY session_id, step_index`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(36) | PK (uuid) |
| `session_id` | VARCHAR(64) | NOT NULL → `active_sessions.session_id` (deleted on session delete) |
| `candidate` | VARCHAR(255) | NOT NULL — denormalized for coverage/admin aggregation |
| `step_index` | INTEGER | NOT NULL — 0-based position in the episode |
| `task_id` | VARCHAR(64) | nullable → `tasks.id` (deleted on task delete) |
| `task_snapshot_json` | TEXT | NOT NULL — immutable observation (task as-asked) |
| `role` | VARCHAR(32) | NOT NULL — `bank \| remediate \| escalate \| pivot \| challenge \| redo` |
| `user_answer` | TEXT | NOT NULL — the action |
| `score` / `max_score` / `fraction` | FLOAT | judge output |
| `reward` | FLOAT | NOT NULL — effective fraction ∈ [0, 1] |
| `state_before_json` | TEXT | NOT NULL — `s_t` (`{global, nodes}` belief snapshot) |
| `state_after_json` | TEXT | NOT NULL — `s_{t+1}` |
| `result_json` | TEXT | NOT NULL — judge result (rationale) |
| `coaching_json` | TEXT | NOT NULL — coach content (misconception, steps) |
| `inherited` | INTEGER | NOT NULL default 0 — 1 = copied from a shared prefix on CoW fork |
| `created_at` | DATETIME | NOT NULL |

Indexes: `uq_session_steps (session_id, step_index)` UNIQUE,
`ix_session_steps_task (task_id)`, `ix_session_steps_candidate (candidate)`.

### `trajectory_shares`
Frozen, identity-stripped episode prefixes (see `docs/collaboration-design.md`).
One row per share; resumes reference the snapshot and only materialize it into
the resumer's `session_steps` on the first write (Copy-on-Write).

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT | PK (opaque share token, 32 hex chars) |
| `source_session_id` | TEXT | NOT NULL — internal only, never exposed |
| `step_index` | INTEGER | NOT NULL — resume boundary (N steps already done) |
| `snapshot_json` | TEXT | NOT NULL — frozen compact session state + prefix step rows (answers stripped) |
| `created_by` | TEXT | NOT NULL — internal only (candidate of the sharer) |
| `created_at` | TEXT | NOT NULL |
| `expires_at` | TEXT | nullable |

Index: `idx_trajectory_shares_source (source_session_id)`.

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

## Candidate identity

The learner key used by `candidate` columns is resolved by
`backend/dependencies.py:resolve_candidate`:

- Signed-in user → their `users.email`.
- Guest → `guest-<X-Guest-Id>` where the header comes from a stable per-browser
  `localStorage` value (regex-guarded `[A-Za-z0-9_-]{8,64}`); a missing/malformed
  header falls back to a fresh ephemeral `guest-<8 hex>` id.

## Schema lifecycle / migrations

`coach/db.py:create_schema()` runs idempotently (guarded per DB file):

1. `Base.metadata.create_all` — creates `tasks`, `session_steps`, `user_skill_beliefs`.
2. Drops removed knowledge-graph/learner tables (`knowledge_nodes`,
   `knowledge_edges`, `learners`, `learner_knowledge_states`, `evidence`,
   `learner_misconceptions`, `learner_frontier`, `assessment_targets`,
   `assessment_tasks`), the superseded `task_attempts` table, and dropped task
   columns (`graph_json`, `target_node_id`, `target_node_slug`,
   `expected_time_min`, `skill`).
3. Adds `context_notes`, `target_text`, `tags_json`, `task_type` to `tasks` if
   absent, and `status` / `resumed_from_share` / `fork_of` / `meta_json` to
   `active_sessions` if absent.
4. `_migrate_skill_beliefs_to_ability` — adds `level`/`key` to
   `user_skill_beliefs`, collapses all legacy per-skill rows to
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