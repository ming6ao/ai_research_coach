# Trajectory Collaboration (MVP) — Copy-on-Write Resume

Status: **Implemented** (matches `coach/steps.py`, `coach/shares.py`,
`backend/v1/sessions.py`, `backend/v1/shares.py`). Companion to
[`docs/data-model.md`](./data-model.md). This is the **minimal viable
collaboration feature**: share a trajectory, resume it anonymously,
Copy-on-Write. Ratings, comments, curation pools, and featured lists are
**explicitly out of scope for MVP** (see Future work).

## Goal

- Any session/episode can be **shared** as an anonymous, resumable trajectory.
- **Resume uses Copy-on-Write**: User B's resumed session *references* a frozen
  share snapshot; the prefix is cloned into B's own rows only when B **continues**
  (first new submit) or **edits** (redo of a shared step) it.
- The data model stays RL-shaped so a future episode-export pipeline is a plain
  `SELECT ... FROM session_steps` (no replay, no blob parsing).

## Concepts / terminology

| Term | Meaning |
|------|---------|
| **Episode** (a.k.a. session) | One candidate's run: an `active_sessions` row plus its `session_steps` rows. |
| **Step** | One scored answer: one RL transition `(s_t, a_t, r_t, s_{t+1})`. |
| **Trajectory** | A lineage: the root episode plus every resume-derived fork (linked via `fork_of`). |
| **Share** | A frozen, **identity-stripped** prefix of an episode at a step boundary, addressable by an opaque token. |
| **CoW fork** | Materializing a share's prefix into the resumer's own `session_steps` rows, triggered on first write. |

## Copy-on-Write resume semantics

Two scopes must be kept distinct (see "Per-user beliefs vs. trajectory data"):

- **Live mastery** — the per-user Gaussian beliefs in `user_skill_beliefs`.
  Strictly per candidate; **never shared between users**.
- **Trajectory data** — the frozen prefix (task snapshots, answers, scores,
  coaching, and the per-step `state_before` / `state_after` path). This is the
  episode's internal state record and *is* what a share copies.

1. **Share** (`POST /api/v1/sessions/{id}/share`, owner, optional `step_index`
   defaulting to the current boundary): the server **freezes a snapshot** of the
   episode prefix at that boundary and stores it on a `trajectory_shares` row.
   The snapshot holds the compact live state at the boundary (task list,
   `index`, asked/viewed/generated bookkeeping, A's belief state `s_N`) **plus
   the N prefix step rows** (each carrying its `state_before_json` /
   `state_after_json`, scores, coaching). No new session is created; nothing is
   copied to any other owner.

2. **Resume** (`POST /api/v1/shared/{token}/resume`): the server resolves B's
   identity (`resolve_candidate`) and creates a **new** `active_sessions` row for
   B:
   - `candidate` = B
   - `state_json` = the snapshot's task list + bookkeeping, with `index = N`,
     but `ability` / node beliefs = **B's own persistent beliefs**
     (`user_skill_beliefs`), **NOT** A's `s_N`.
   - `resumed_from_share` = the share token (prefix is still just a reference)
   - `fork_of` = the source session id (internal lineage, never surfaced)
   - **No `session_steps` rows are created yet.**
   - The first presented task is chosen by the normal picker from **B's own**
     beliefs; the prefix is shown as read-only history from the snapshot (zero
     clone cost).

3. **Continue → CoW fork** (B's first submit on a resumed session): `submit_answer`
   sees `resumed_from_share` set and **materializes** the N prefix steps into B's
   own `session_steps` rows (`inherited = 1`) from the snapshot, clears
   `resumed_from_share`, then inserts B's new step (index N) normally. The
   inherited rows keep A's `state_before` / `state_after` as historical data —
   **no belief updates are applied for them**. B's new step's `state_before` =
   B's own live beliefs. From here B's episode is fully self-contained (and
   trivially exportable).

4. **Edit → CoW fork** (`POST /api/v1/sessions/{id}/redo` `{step_index, answer}`
   on an inherited prefix step): materialize the prefix up to `step_index - 1`,
   **re-judge** `step_index` with B's answer, **compute its state transition
   from B's own live beliefs** (not A's prefix path), **discard any shared steps
   after `step_index`** (they were never B's own), and set `index =
   step_index + 1`. Simplest correct semantics: fork-at-k, truncate the tail,
   continue.

### Per-user beliefs vs. trajectory data

- `user_skill_beliefs` is keyed `(candidate, level, key)` — the persistent
  mastery measurement. It is **never copied or shared between users**. Sharing a
  trajectory shares *data*, not mastery.
- The per-step `state_before` / `state_after` in a prefix are the **episode's
  internal RL state path** — part of the trajectory artifact. On resume they are
  preserved verbatim (so the copied prefix stays internally consistent), but
  they do **not** become B's live ability.
- Consequence: B's episode may show a belief **jump** at the boundary (A's `s_N`
  from the last inherited step → B's own live beliefs at B's first step). That is
  correct and honest — they are different agents. The inherited prefix reads as
  demonstration/context; B's continuation is B's own. For offline RL this is the
  natural "reset at the demonstrated prefix" boundary, and `inherited = 1`
  marks it in the data.
- "As if B did steps 1–3 exactly as A did" now means: the *trajectory content*
  (tasks, answers, scores, coaching) is identical — B experiences the same steps
  and outcomes. It does **not** mean B inherits A's measured mastery.

**No user information is shared:** the snapshot strips `candidate`,
`created_by`, `source_session_id`, emails, and guest ids, and does **not**
include A's code answers. Review of a share shows tasks, scores, and coaching
only.

## RL mapping

| RL concept | Model |
|------------|-------|
| episode | `active_sessions` row + its `session_steps` rows |
| timestep `t` | `session_steps.step_index` (0-based; `index` = number done) |
| observation `o_t` | `session_steps.task_snapshot_json` (immutable, as-asked) |
| state `s_t` | global + domain/area/skill Gaussian beliefs (`state_before_json`) |
| action `a_t` | `session_steps.user_answer` |
| reward `r_t` | `session_steps.reward` = effective fraction ∈ [0,1] |
| next state `s_{t+1}` | `session_steps.state_after_json` |
| done | `active_sessions.status = 'done'` (or `next_task is None`) |
| trajectory lineage | `active_sessions.fork_of` + share provenance |

### RL signal sufficiency

The schema captures the **core MDP tuple** faithfully and deterministically
(observation = task snapshot, state = beliefs, action = code, reward =
effective fraction, next-state, done, lineage). That is sufficient for
**offline data collection, behavior cloning, reward prediction, and a
closed-loop learner-side MDP**. It is *not* yet sufficient for rich RL training,
especially over the **teaching policy** (which question to ask next — the
natural RL target in this app):

**Gaps to close later (future export/step columns):**

- **Selection decision (biggest gap).** The step stores only the chosen task
  snapshot, not *why* it was chosen — the picker's EIG values, exploration
  bonuses, same-area penalty, remediation mode (`remediate/escalate/pivot/...`),
  and follow-up root. Teaching-policy RL needs these per-step features.
- **Discrete success signal.** `fraction` is continuous; add a binary
  `solved = fraction >= 0.8` flag for sparse-reward / threshold use.
- **Reward shaping.** Today the reward is task-local only. For teaching-policy
  RL, shape it with episode-level signals: Δmastery (global/domain/area/skill),
  coaching effectiveness (did the candidate solve the follow-up), time
  efficiency.
- **Temporal / engagement / answer-content features.** Time per step, streak,
  spacing, answer length, diff vs scaffold, signature match — useful for
  richer reward models.
- **Human quality labels.** Per-step ratings/comments (deferred from MVP) are
  the RLHF-style reward channel for trajectory quality.

What the schema already guarantees (good): deterministic, auditable transitions;
immutable observations (task snapshots); identity-free share/resume; per-step
`state_before/after`; and trajectory lineage.

## Data model changes

### `active_sessions` — episode header (changed)

`session_json` keeps its name but its **content changes**: it holds the compact
live state only (no trajectory). `feedback_json` is dropped; per-step data moves
to `session_steps`.

| Column | Type | Notes |
|--------|------|-------|
| `session_id` | TEXT | PK |
| `candidate` | TEXT | NOT NULL — owner |
| `status` | TEXT | NOT NULL — `active \| done` |
| `session_json` | TEXT | compact live state: `{tasks:[TaskSnapshot], index, asked_task_ids, generated_task_ids, ability, task_progress, phase_attempts, submission_index}` |
| `resumed_from_share` | TEXT | nullable — share token while the prefix is still a CoW reference (cleared on first write) |
| `fork_of` | TEXT | nullable — internal lineage (source session id) |
| `meta_json` | TEXT | nullable — `{node, initial_question, eval_model}` |
| `updated_at` | TEXT | NOT NULL |
| ~~`session_json` (old)~~ | | now compact only |
| ~~`feedback_json`~~ | | dropped — its records become `session_steps` rows |

Index: `idx_active_sessions_candidate (candidate)`.

### `session_steps` — one row per RL transition (new)

Supersedes `task_attempts` **and** `feedback_json`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(36) | PK (uuid) |
| `session_id` | VARCHAR(64) | NOT NULL → `active_sessions.session_id` (cascade delete) |
| `candidate` | VARCHAR(255) | NOT NULL — denormalized (added in implementation for cheap coverage/admin aggregation) |
| `step_index` | INTEGER | NOT NULL — 0-based position in the episode |
| `task_id` | VARCHAR(64) | nullable → `tasks.id` (may be deleted) |
| `task_snapshot_json` | TEXT | NOT NULL — immutable observation (as-asked) |
| `role` | TEXT | `bank \| remediate \| escalate \| pivot \| challenge \| redo` |
| `user_answer` | TEXT | NOT NULL — the action |
| `score` / `max_score` / `fraction` | REAL | judge output |
| `reward` | REAL | NOT NULL — effective fraction ∈ [0,1] |
| `state_before_json` | TEXT | NOT NULL — `s_t` |
| `state_after_json` | TEXT | NOT NULL — `s_{t+1}` |
| `result_json` | TEXT | NOT NULL — judge result (rationale) |
| `coaching_json` | TEXT | NOT NULL — coach content (misconception, steps) |
| `inherited` | INTEGER | NOT NULL default 0 — 1 = copied from a shared prefix on CoW fork |
| `created_at` | DATETIME | NOT NULL |

Indexes: `uq_session_steps (session_id, step_index)` UNIQUE,
`ix_session_steps_task (task_id)`, `ix_session_steps_candidate (candidate)`.

### `trajectory_shares` — frozen share snapshots (new)

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR(36) | PK (uuid — used as the share token) |
| `source_session_id` | VARCHAR(64) | NOT NULL — internal only |
| `step_index` | INTEGER | NOT NULL — resume boundary (N steps already done) |
| `snapshot_json` | TEXT | NOT NULL — frozen, identity-stripped prefix (live state + N step rows) |
| `created_by` | VARCHAR(255) | NOT NULL — internal only |
| `created_at` | DATETIME | NOT NULL |
| `expires_at` | DATETIME | nullable |

Index: `ix_trajectory_shares_source (source_session_id)`.

### `task_attempts` — deprecated, dropped

`session_steps` carries everything `task_attempts` had plus episode identity;
coverage/admin consumers migrate to `session_steps`.

### Dropped from the earlier design (not MVP)

`trajectories` table, `step_comments`, ratings, featured pool, `visibility` /
`share_token` columns on `active_sessions`, `include_answers` / `mode` on shares.
Lineage is just `fork_of`; sharing is just a `trajectory_shares` row.

## Schema lifecycle / migration

- `create_schema()` creates `session_steps` and `trajectory_shares` and adds the
  new `active_sessions` columns idempotently.
- **Backfill**: `coach.steps.backfill_session_steps()` reconstructs
  `session_steps` from legacy `session_json` + `feedback_json` by deterministic
  Bayesian replay (old sessions become exportable episodes). Idempotent —
  sessions that already have steps are skipped.
- `task_attempts` is dropped. The legacy `feedback_json` column is dropped
  **only once** every session has been backfilled (or has no legacy results), so
  no per-step data is lost.
- Coverage/admin consumers read `session_steps` instead of `task_attempts`.
- Shares are created fresh; no legacy migration needed.

## API (MVP, implemented)

| Endpoint | Auth | Notes |
|----------|------|-------|
| `POST /api/v1/sessions/{id}/share` `{step_index?}` | owner | freeze + store snapshot; returns `{token, url}` |
| `GET /api/v1/shared/{token}` | token only | open share: trajectory info + prefix steps (tasks, scores, coaching — no identity, no answers) |
| `POST /api/v1/shared/{token}/resume` | resolves B | create B's CoW session (B's own beliefs); returns normal session view + first task |
| `POST /api/v1/sessions/{id}/redo` `{step_index, answer}` | owner | edit-triggered CoW fork: re-judge step, recompute beliefs from B's live state, truncate tail |
| `DELETE /api/v1/shared/{token}` | sharer | revoke a share |

Resuming a share that belongs to the sharer themselves simply opens the
referenced prefix; resuming materializes nothing until the first write.

## UI (MVP, implemented)

- **Share**: a "Share trajectory" button in `ChatView` (shown once the session
  has at least one result) copies the share URL (`/shared/{token}`) to the
  clipboard.
- **Shared preview**: a `/shared/{token}` route (`SharedView`) renders the
  prefix as read-only review bubbles (task prompts, score chips, coaching) with
  a prominent **"Resume this trajectory"** button.
- **Resume**: clicking it creates B's session and lands in the normal chat view.
  The prefix renders as read-only history; the next question is active. B's
  first submit silently triggers the CoW fork.
- **Redo**: API implemented (`POST /sessions/{id}/redo`); no dedicated UI
  control yet (covered by backend tests).

## Performance

- Share / resume: O(N) to read the snapshot, O(1) to write (no clone).
- Continue / redo: one O(N) materialization on the **first** write, then
  O(1) per step (single `INSERT` + compact `UPDATE state_json`).
- Review of an unreforged prefix reads the snapshot; review of a forked session
  scans `session_steps` by `(session_id, step_index)`.

## Privacy

- Share access is token-based; no authentication leaks identity.
- `candidate`, `created_by`, `source_session_id`, and `fork_of` are internal
  only; the snapshot and all share responses exclude identity and A's answers.
- A consent/opt-in flag is deferred until an external consumer exists.

## Future work (explicitly out of MVP)

- Per-step **comments / ratings** and a **featured trajectory pool** (human
  quality signal for curating the "best" trajectories).
- `include_answers` toggle for review-style shares.
- Episode **export pipeline** — now a plain `SELECT ... FROM session_steps
  ORDER BY session_id, step_index` + session header; no replay, no parsing.
- **RL signal enrichment** (see "RL signal sufficiency"): store the picker's
  selection decision/features per step, a binary `solved` flag, per-step
  timing/engagement metrics, and later answer-content features and human
  ratings as quality reward.