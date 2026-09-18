# AI Research Coach

A coaching app that probes and teaches AI/ML coding skills. It asks adaptive
coding questions (Bayesian expected-information-gain selection), judges each
answer with an LLM, and coaches the candidate through their gaps step by step.
There is **no summative score, report, or verdict** — the app keeps a live
overall ability belief and shows the candidate's progress as overall mastery % plus
the judge's gap notes on answered questions.

It is a single FastAPI + Vite app (no ADK agent). Questions live in the
`tasks` DB table (not a YAML file) — users author their own via
`POST /api/v1/tasks` (or the curator UI's quick-authoring assistant).

## Architecture

```
FastAPI (backend/main.py, backend/v1/*, backend/auth_routes.py)
        │
        ├── auth (backend/auth.py + google_auth.py)
        ├── sessions (backend/dependencies.py)
        │
        ├── coach/              parent assessment engine
        │   ├── score.py        Bayesian ability belief (picker inputs)
        │   ├── area_score.py   per-node beliefs + read-time shrinkage
        │   ├── picker.py       EIG bank-task selection
        │   ├── session.py      tasks/results/ability + step progress
        │   ├── selection.py    hybrid next-task selection (step continuation)
        │   ├── remediation.py  judge-driven follow-up tasks
        │   ├── solvability.py  P(solve) estimate + adaptive difficulty ladder
        │   ├── taxonomy.py     closed domain/area/skill vocabulary
        │   ├── tasks.py        DB task bank + steps + ability beliefs
        │   ├── steps.py        RL-shaped per-step session storage
        │   ├── task_decomposer.py  LLM: plain-English context + follow-up tasks
        │   ├── judge.py        LLM judge (score + rationale + coaching)
        │   ├── db.py           single SQLite connection + schema
        │   └── migrate.py      taxonomy/delivery migration + coverage CLI
```
(no `learner/` package — the overall ability belief is the only mastery model)

LLM calls live in exactly two places: `coach/judge.py` (judge + coach) and
`coach/task_decomposer.py` (context notes + follow-up generation).

## Project structure

```
ai_research_coach/
├── backend/
│   ├── main.py            # FastAPI app
│   ├── v1/                # canonical REST API (/api/v1/*): sessions, tasks, users
│   ├── auth_routes.py     # /api/auth/* endpoints (Google OAuth)
│   ├── admin_routes.py    # /admin/* endpoints (taxonomy, reset, candidate wipe)
│   ├── auth.py            # session tokens (Bearer header or HttpOnly cookie)
│   ├── csrf.py            # Origin check for cookie-authenticated writes
│   └── google_auth.py     # Google OAuth (stdlib only, DB-backed state)
├── coach/
│   ├── score.py / picker.py           # Bayesian probing engine
│   ├── session.py         # candidate session state
│   ├── selection.py       # hybrid next-task selection
│   ├── remediation.py     # judge-driven follow-up planner
│   ├── solvability.py     # P(solve) + difficulty ladder
│   ├── tasks.py           # DB task bank (tasks/session_steps/user_skill_beliefs)
│   ├── task_decomposer.py # LLM context notes + follow-up generation
│   ├── judge.py           # LLM judge (score + rationale + coaching response)
│   └── db.py              # single connection module (data/coach.db)
├── frontend/              # React 19 + TypeScript + Vite + Tailwind v4
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env from the committed template (never commit .env itself):
cp .env.example .env
# Then set GOOGLE_API_KEY=... in .env (required). In production, prefer
# real env vars / your platform's secret manager over a .env file.

# Optional: Google login (set BOTH or NEITHER)
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...

python check_env.py          # verify env + model connectivity
./run.sh                     # backend :8001, frontend :5173
```

## How it works

1. **Start** — `POST /api/v1/sessions` creates a session. The candidate is
   derived from the bearer token (email) or a fresh `guest-<hex>` id. The first
task is picked by `pick_next_task`.
2. **Task loop** — the candidate writes code; the LLM judge returns a score, a rationale, and a
   **coaching response** (misconception + step-by-step walkthrough with code). Every task is
   step-by-step: its steps are delivered one at a time and the candidate's code is carried
   forward via `previous_code`.
3. **Teaching pause** — the UI never auto-advances. The coaching response and per-part
   results are shown; the candidate clicks **Next question** / **Next step** / **Retry step**
   to continue. The next task is chosen by the hybrid `pick_next_task`:
1. a pending generated task surfaces first,
2. an active step task continues (next step, or the same step after a failed attempt),
3. otherwise a judge-driven follow-up fires after a weak answer or a named gap (a *simpler* generated task drills the judge's gap text),
4. otherwise the EIG bank picker selects the informative task,
5. a fresh generated challenge when the bank is exhausted, else `None`.
4. **Progress** — when `next_task` is `null`, the candidate is done.
   `POST /api/v1/sessions/{id}/completion` returns the progress snapshot (overall ability).
   Sessions stay in `active_sessions` for resume/history; "done" is derived
   from the session.

## Question selection

- **Bayesian probing** (`coach/score.py` + `coach/picker.py`): a single Gaussian belief
  `N(mean, variance)` over overall ability, updated by the judge score. The bank picker maximizes
  `EIG / expected_time`; when the bank is exhausted a fresh generated challenge keeps the session
  going until the candidate finishes.
- **Step-by-step tasks**: the judge scores the active step; passing
  (`score >= pass_score`, default `round(0.7 * max_score)`) or reaching
  `PHASE_MAX_ATTEMPTS` advances to the next step with the candidate's prior code.
- **Follow-ups** (`coach/remediation.py`): the judge's gap text
  (misconception/feedback) drives one simpler drill task on weak answers;
  clean solves generate nothing. Budget caps keep the loop finite.

## API surface

All v1 resources return a `{data}` envelope; list endpoints add
`{meta: {page, page_size, total}}`.

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/sessions` `{task_ids?}` | New session → `{id, candidate, total_tasks, task_index, current_task}` (201) |
| `GET /api/v1/sessions/{id}` | Resume a session → `{current_task, results, ability}` |
| `POST /api/v1/sessions/{id}/answers` `{task_id, answer}` | Score + coach + `next_task` + `ability_update` (+ `already_answered` on replay) |
| `POST /api/v1/sessions/{id}/completion` | Progress snapshot `{done, ability, mastery}` |
| `DELETE /api/v1/sessions/{id}` | Delete a session (204, ownership-guarded) |
| `POST /api/v1/tasks` `{parts, tags, task_type?, language?, is_public?, context_notes?}` | Create a user question (201; `tags` required; every step needs `prompt`/`tags`/`max_score`/`difficulty`/`scaffold`) |
| `GET /api/v1/tasks?q=&page=&page_size=` | List visible tasks (paginated) |
| `GET /api/v1/tasks/{id}` | Task detail |
| `PATCH /api/v1/tasks/{id}` | Edit a question (owner or admin) |
| `DELETE /api/v1/tasks/{id}` | Delete a question + its attempts (owner or admin; system rows admin-only) |
| `GET /api/v1/me` | Current user |
| `GET /api/v1/me/sessions` | My sessions with a `done` flag (paginated) |
| `DELETE /api/v1/me/data` | Delete my sessions + attempts + beliefs + owned tasks |
| `/api/auth/*` | Google login / me / logout |
| `/admin/*` | Admin taxonomy (`/taxonomy`) + activity reset (`/reset`, `/reset/preview`) + owner-or-admin candidate wipe (`/candidate/{candidate}`, `/candidate/{candidate}/summary`) |

## Persistence

Single SQLite file `data/coach.db` (gitignored, created on first run) with 7
tables: `users`, `auth_tokens`, `active_sessions`, `oauth_states`, `tasks`,
`session_steps`, `user_skill_beliefs`. `coach/db.py` is the
single connection module (it drops removed columns/tables and collapses legacy
per-skill beliefs so old databases converge). Per-step data lives in
`session_steps`; overall + per-area mastery persists across sessions in
`user_skill_beliefs`. Generated follow-ups link via
`parent_task_id`/`target_text`. Each task optionally carries
`context_notes` (plain-English prerequisites/confusions).

## How to extend (no code changes)

- **Add a question**: `POST /api/v1/tasks` with `parts` (one or more steps,
each requiring `prompt`/`tags`/`max_score`/`difficulty`/`scaffold`) and optional
`task_type`/`language`/`is_public`/`context_notes`. User rows are private by
default (guests create public rows); generated follow-ups link via
`parent_task_id`/`target_text`. The curator UI's AI assistant can draft the
whole body from step prompts via `POST /api/v1/tasks/draft`.
- **Change the model**: set `EVAL_MODEL` in `.env` (e.g. `gemini-3.5-flash-lite`).

## Environment variables

See the committed `.env.example` for the full template. Local dev uses a
gitignored `.env`; production should use real env vars / a secret manager.
The backend logs warnings for partial OAuth config or bad numerics on
startup, and fails fast when `APP_ENV=production` and required config is
missing (see `coach/env_config.py`).

```bash
GOOGLE_API_KEY=...              # Required
EVAL_MODEL=gemini-3.5-flash-lite   # Judge/coach + decomposition model
EVAL_RETRY_ATTEMPTS=5           # Retry attempts (all layers)
EVAL_RETRY_INITIAL_DELAY=1.0    # Initial backoff (seconds)
EVAL_RETRY_MAX_DELAY=30.0       # Max backoff (seconds)
GOOGLE_CLIENT_ID=...            # Google login (optional, set BOTH or NEITHER)
GOOGLE_CLIENT_SECRET=...        # Google login (optional, set BOTH or NEITHER)
GOOGLE_REDIRECT_URI=...         # OAuth callback (default localhost:8001/...)
FRONTEND_URL=...                # Public frontend URL (+ CORS allowlist)
CORS_ORIGINS=...                # Extra comma-separated CORS origins (no '*')
ADMIN_EMAILS=you@example.com    # Admin allowlist for /admin deletes (comma-separated)
LEARNING_PARTNER_DB_URL=...     # Optional SQLite URL override (default data/coach.db)
APP_ENV=development             # Set to `production` to fail fast on bad config
```

## Resilience & retry

Transient failures (rate limits `429`, server errors `5xx`, timeouts `408/504`)
are handled with exponential backoff retries (5 attempts, 1s → 30s, jitter).
Answer submission is idempotent: re-submitting a scored task returns the stored
result with `already_answered: true` without double-counting.

## Migrating the bank

The question bank lives in the `tasks` table. Tasks are tagged with the closed
3-level taxonomy (domain → area → skill) in `coach/taxonomy.py`; tags are
**required** (a missing/invalid/non-leaf primary is rejected with 422).

When the taxonomy changes, migrate existing rows in place with the admin CLI
(run it with the server stopped):

```bash
python -m coach.migrate                 # dry run: report what would change
python -m coach.migrate --apply         # back up the DB, then migrate in place
python -m coach.migrate coverage        # per-leaf-skill bank coverage
```

`--apply` rewrites task and step tags, per-node belief rows,
active-session snapshots, and step snapshots, preserving task ids,
owners, and attempt links. Tasks whose primary skill was retired can be
deleted (`--on-unmapped delete`, default), retagged (`--on-unmapped fallback
--fallback <leaf>`), or left as-is (`--on-unmapped keep`). The one-time
old→new map lives in `coach/taxonomy_migration.py`.

To wipe the bank instead, `POST /admin/reset?wipe_tasks=true` (admin-only)
clears activity and every task. There is no separate seed file: the `tasks`
table is the single source of truth, authored via `POST /api/v1/tasks` or the
curator UI.

## Tests

```bash
.venv/bin/python -m pytest                 # backend
cd frontend && npm run lint && npx tsc -b  # frontend checks
cd frontend && npm test                    # frontend tests
cd frontend && npm run build               # production build
```