# AI Research Coach

A coaching app that probes and teaches AI/ML coding skills. It asks adaptive
coding questions (Bayesian expected-information-gain selection), judges each
answer with an LLM, and coaches the candidate through their gaps step by step.
There is **no summative score, report, or verdict** — the app keeps a live
per-skill belief and shows the candidate's progress as skill confidence plus
the judge's gap notes on answered questions.

It is a single FastAPI + Vite app (no ADK agent). Questions live in the
`tasks` DB table (not a YAML file) — users enter their own via
`POST /api/tasks` or the `initial_question` field on `/api/start`.

## Architecture

```
FastAPI (backend/main.py, backend/routes.py)
        │
        ├── auth (backend/auth.py + google_auth.py)
        ├── sessions (backend/dependencies.py)
        │
        ├── coach/              parent assessment engine
        │   ├── score.py        Bayesian skill beliefs (picker inputs)
        │   ├── picker.py       EIG bank-task selection
        │   ├── hints.py        requestable hints + score penalty
        │   ├── session.py      tasks/results/skill_states (no mode)
        │   ├── selection.py    hybrid next-task selection
        │   ├── remediation.py  judge-driven follow-up tasks
        │   ├── solvability.py  P(solve) estimate + adaptive difficulty ladder
        │   ├── tasks.py        DB task bank + attempts + skill beliefs
        │   ├── task_decomposer.py  LLM: plain-English context + follow-up tasks
        │   ├── judge.py        LLM judge (score + rationale + coaching)
        │   └── db.py           single SQLite connection + schema
```
(no `learner/` package — per-skill beliefs are the only mastery model)

LLM calls live in exactly two places: `coach/judge.py` (judge + coach) and
`coach/task_decomposer.py` (context notes + follow-up generation).

## Project structure

```
ai_research_coach/
├── backend/
│   ├── main.py            # FastAPI app
│   ├── routes.py          # /api/* endpoints
│   ├── admin_routes.py    # /admin/* endpoints (table browser + manage)
│   ├── auth.py            # bearer tokens
│   └── google_auth.py     # Google OAuth (stdlib only)
├── coach/
│   ├── score.py / picker.py / hints.py   # Bayesian probing engine
│   ├── session.py         # candidate session state
│   ├── selection.py       # hybrid next-task selection
│   ├── remediation.py     # judge-driven follow-up planner
│   ├── solvability.py     # P(solve) + difficulty ladder
│   ├── tasks.py           # DB task bank (tasks/task_attempts/user_skill_beliefs)
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

# Create .env with your Gemini API key:
echo 'GOOGLE_API_KEY="YOUR_API_KEY"' > .env

# Optional: Google login
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...

python check_env.py          # verify env + model connectivity
./run.sh                     # backend :8001, frontend :5173
```

## How it works

1. **Start** — `POST /api/start` (optionally with a custom `initial_question`)
   creates a session. The candidate is derived from the bearer token (email) or
   a fresh `guest-<hex>` id. The first task is picked by `pick_next_task`.
2. **Task loop** — the candidate writes code and may reveal hints (which reduce
   effective mastery). The LLM judge returns a score, a rationale, and a
   **coaching response** (misconception + step-by-step walkthrough with code).
3. **Teaching pause** — the UI never auto-advances. The coaching response is
   shown; the candidate clicks **Next question** to continue. The next task is
   chosen by the hybrid `pick_next_task`:
1. a pending generated task surfaces first,
2. otherwise a judge-driven follow-up fires after a weak answer or a named
   gap (a *simpler* generated task drills the judge's gap text),
3. otherwise the EIG bank picker selects the informative task,
4. `None` when the bank is exhausted and no follow-up remains.
4. **Progress** — when `next_task` is `null`, the candidate is done.
   `POST /api/complete` returns the progress snapshot (per-skill confidence).
   Sessions stay in `active_sessions` for resume/history; "done" is derived
   from the session.

## Question selection

- **Bayesian probing** (`coach/score.py` + `coach/picker.py`): a Gaussian belief
  `N(mean, variance)` per skill, updated by the judge score minus the hint
  penalty. The bank picker maximizes `EIG · coverage / expected_time`
  and the session ends when the task bank is exhausted.
- **Follow-ups** (`coach/remediation.py`): the judge's gap text
  (misconception/feedback) drives one simpler drill task on weak answers;
  clean solves generate nothing. Budget caps keep the loop finite.

## API surface

| Endpoint | Purpose |
|----------|---------|
| `POST /api/start` `{initial_question?, task_ids?, skill?}` | New session → `{session_id, candidate, message, first_task}` |
| `POST /api/tasks` `{prompt, skill?, scaffold?, difficulty?, hints?, is_public?, context_notes?}` | Create a user question → `{task}` |
| `GET /api/tasks?skill=` | List visible tasks |
| `GET /api/tasks/{id}` | Task detail |
| `POST /api/submit` `{session_id, task_id, answer, hints_used}` | Score + coach + `next_task` + `skill_update` |
| `POST /api/complete` `{session_id}` | Progress snapshot `{done, skill_states}` |
| `POST /api/session/open` `{id}` | Resume a session → `{current_task, results, skill_states}` |
| `GET /api/sessions` | Candidate's sessions with a `done` flag |
| `DELETE /api/sessions/active/{id}` | Delete an active session (ownership-guarded) |
| `DELETE /api/sessions/clear/{candidate}` | Delete sessions + attempts + beliefs + owned tasks |
| `/api/auth/*` | Google login / me / logout |
| `/admin/*` | Admin endpoints: table browser (`/tables`, `/table/{name}`) + manage endpoints below |
| `GET /admin/tasks?owner=&skill=&q=` | List questions with attempt counts |
| `PATCH /admin/tasks/{id}` `{context_notes}` | Edit a question's plain-English context (owner or admin) |
| `GET /admin/candidate/{candidate}/summary` | Per-table row counts preview (owner or admin) |
| `DELETE /admin/candidate/{candidate}` | Full candidate wipe (owner or admin) |
| `DELETE /admin/tasks/{id}` | Delete a question + its attempts (owner or admin; system rows admin-only) |

## Persistence

Single SQLite file `data/coach.db` (gitignored, created on first run) with 6
tables: `users`, `auth_tokens`, `active_sessions`, `tasks`, `task_attempts`,
`user_skill_beliefs`. `coach/db.py` is the single connection module (it drops
the removed knowledge-graph/learner tables on startup so old databases
converge). Per-task progress lives in `task_attempts`; per-skill mastery
persists across sessions in `user_skill_beliefs`. Generated follow-ups link
via `parent_task_id`/`target_text`. Each task optionally carries
`context_notes` (plain-English prerequisites/confusions).

## How to extend (no code changes)

- **Add a question**: `POST /api/tasks` with `prompt`, `skill`, and optional
  `scaffold`/`difficulty`/`hints`/`context_notes`. Or pass `initial_question` to
  `/api/start`. The `skill` tag is a free-form id — a new tag starts a fresh
  per-skill belief. User rows are private by default (guests create public
  rows); generated follow-ups link via `parent_task_id`/`target_text`.
- **Change the model**: set `EVAL_MODEL` in `.env` (e.g. `gemini-3.5-flash-lite`).

## Environment variables

```bash
GOOGLE_API_KEY=...              # Required
EVAL_MODEL=gemini-3.5-flash-lite   # Judge/coach + decomposition model
EVAL_RETRY_ATTEMPTS=5           # Retry attempts (all layers)
EVAL_RETRY_INITIAL_DELAY=1.0    # Initial backoff (seconds)
EVAL_RETRY_MAX_DELAY=30.0       # Max backoff (seconds)
GOOGLE_CLIENT_ID=...            # Google login (optional)
GOOGLE_CLIENT_SECRET=...        # Google login (optional)
ADMIN_EMAILS=you@example.com    # Admin allowlist for /admin deletes (comma-separated)
```

## Resilience & retry

Transient failures (rate limits `429`, server errors `5xx`, timeouts `408/504`)
are handled with exponential backoff retries (5 attempts, 1s → 30s, jitter).
`/api/submit` is idempotent: re-submitting a scored task returns the stored
result without double-counting.

## Tests

```bash
.venv/bin/python -m pytest                 # backend
cd frontend && npm run lint && npx tsc -b  # frontend checks
cd frontend && npm test                    # frontend tests
cd frontend && npm run build               # production build
```