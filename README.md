# AI Research Coach

A coaching app that probes and teaches AI/ML coding skills. It asks adaptive
coding questions (Bayesian expected-information-gain selection), judges each
answer with an LLM, and coaches the candidate through their gaps step by step.
There is **no summative score, report, or verdict** — the app keeps a live
per-skill belief and a per-knowledge-node learner model, and shows the
candidate's progress as confidence + misconceptions + next actions.

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
        │   ├── remediation.py  frontier remediation + consolidation successors
        │   ├── solvability.py  P(solve) estimate + adaptive difficulty ladder
        │   ├── tasks.py        DB task bank + attempts + skill beliefs
        │   ├── task_decomposer.py  LLM: task → KG nodes; remediation/variant tasks
        │   ├── judge.py        LLM judge (score + rationale + coaching)
        │   └── db.py           single SQLite connection + schema
        │
        └── learner/            learner model (one module per topic)
            ├── engine.py       LearnerEngine facade + hybrid pick_next_task
            ├── graph/states/evidence/update
            ├── misconception/frontier/policy/orchestrator
            └── traversal/types/interfaces/container  (numeric, deterministic)
```

LLM calls live in exactly two places: `coach/judge.py` (judge + coach) and
`coach/task_decomposer.py` (decomposition + remediation generation). Everything
in the learner model is deterministic.

## Project structure

```
ai_research_coach/
├── backend/
│   ├── main.py            # FastAPI app
│   ├── routes.py          # /api/* endpoints
│   ├── admin_routes.py    # /admin/* debug endpoints
│   ├── admin_page.py      # standalone admin/debug HTML page
│   ├── auth.py            # bearer tokens
│   └── google_auth.py     # Google OAuth (stdlib only)
├── coach/
│   ├── score.py / picker.py / hints.py   # Bayesian probing engine
│   ├── session.py         # candidate session state
│   ├── remediation.py     # remediation + consolidation planner
│   ├── solvability.py     # P(solve) + difficulty ladder
│   ├── tasks.py           # DB task bank (tasks/task_attempts/user_skill_beliefs)
│   ├── task_decomposer.py # LLM decomposition + remediation/variant generation
│   ├── judge.py           # LLM judge (score + rationale + coaching response)
│   └── db.py              # single connection module (data/coach.db)
├── learner/               # learner model, one module per topic
│   ├── engine.py          # LearnerEngine facade + hybrid pick_next_task
│   ├── graph.py           # knowledge nodes/edges + traversal + SQL tables
│   ├── states.py          # learners + mastery states + SQL tables
│   ├── evidence.py        # immutable observation records + SQL table
│   ├── update.py          # Bayesian mastery/uncertainty engine
│   ├── misconception.py   # detection/tracking + SQL table
│   ├── frontier.py        # readiness computation + SQL table
│   ├── policy.py          # next-action selection
│   ├── orchestrator.py    # evidence assessors + assess→update loop
│   └── traversal.py / types.py / interfaces.py / container.py
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
2. otherwise the learner model's frontier drives remediation (a *simpler*
   generated task drills the highest-information-gain node),
3. otherwise a consolidation successor fires after a strong answer with
   residual uncertainty (a *similar* task tuned to ~80% P(solve)),
4. otherwise the EIG bank picker selects the informative task,
5. `None` when the bank is exhausted and no remediation remains.
4. **Progress** — when `next_task` is `null`, the candidate is done.
   `POST /api/complete` returns the progress snapshot (per-skill confidence +
   per-node states, misconceptions, next action). Sessions stay in
   `active_sessions` for resume/history; "done" is derived from the session.

## Question selection

- **Bayesian probing** (`coach/score.py` + `coach/picker.py`): a Gaussian belief
  `N(mean, variance)` per skill, updated by the judge score minus the hint
  penalty. The bank picker maximizes `EIG · coverage / expected_time`
  and the session ends when the task bank is exhausted.
- **Remediation** (`coach/remediation.py` + `learner/`): per-node
  mastery/uncertainty drives the frontier/policy; incorrect/partial answers,
  active misconceptions, and high-uncertainty nodes generate a simpler drill task.

## API surface

| Endpoint | Purpose |
|----------|---------|
| `POST /api/start` `{initial_question?, task_ids?, skill?}` | New session → `{session_id, candidate, message, first_task, learner}` |
| `POST /api/tasks` `{prompt, skill?, scaffold?, difficulty?, hints?, is_public?}` | Create a user question → `{task}` |
| `GET /api/tasks?skill=` | List visible tasks |
| `GET /api/tasks/{id}` | Task detail |
| `POST /api/submit` `{session_id, task_id, answer, hints_used}` | Score + coach + `next_task` + `skill_update` + `learner_update` |
| `POST /api/complete` `{session_id}` | Progress snapshot `{done, skill_states, learner}` |
| `POST /api/session/open` `{id}` | Resume a session → `{current_task, results, skill_states, learner}` |
| `GET /api/sessions` | Candidate's sessions with a `done` flag |
| `DELETE /api/sessions/active/{id}` | Delete an active session (ownership-guarded) |
| `DELETE /api/sessions/clear/{candidate}` | Delete sessions + learner rows + attempts + beliefs + owned tasks |
| `/api/auth/*` | Google login / me / logout |
| `/admin/*` | Debug endpoints (graph, learner detail, stats, SkillState) + Manage endpoints below |
| `GET /admin/tasks?owner=&skill=&q=` | List questions with attempt counts |
| `GET /admin/candidate/{candidate}/summary` | Per-table row counts preview (owner or admin) |
| `DELETE /admin/candidate/{candidate}` | Full candidate wipe (owner or admin) |
| `DELETE /admin/tasks/{id}` | Delete a question + its attempts (owner or admin; system rows admin-only) |

## Persistence

Single SQLite file `data/coach.db` (gitignored, created on first run) with 13
tables: `users`, `auth_tokens`, `active_sessions`, `knowledge_nodes`,
`knowledge_edges`, `learners`, `learner_knowledge_states`, `evidence`,
`learner_misconceptions`,
`learner_frontier`, plus `tasks`, `task_attempts`, `user_skill_beliefs`.
`coach/db.py` is the single connection module. The learner
state is **derived** from the append-only `evidence` table, so history is always
recomputable. Per-task progress lives in `task_attempts`; per-skill mastery
persists across sessions in `user_skill_beliefs`. Task→node mapping is ephemeral (derived from the decomposer at
submit time).

## Learner model (flat `learner/`)

- The learner package (one module per topic — models, services, and SQL
  persistence for that topic live together) keeps per-node mastery/uncertainty
  beliefs that drive the frontier/policy/remediation.
- `learner/engine.py` (`LearnerEngine`) is the single facade:
  `ensure_learner`, `bootstrap_task`, `bootstrap_generated_task`,
  `record_submission`, `learner_snapshot`, plus the hybrid `pick_next_task` and
  `clear_learner_data(candidate)`.
- Candidate identity lives on the `learners.candidate` column (UNIQUE).
- CLI inspector:

```bash
python -m learner.engine --demo          # canned learner, no API key
python -m learner.engine alice@example.com
```

## How to extend (no code changes)

- **Add a question**: `POST /api/tasks` with `prompt`, `skill`, and optional
  `scaffold`/`difficulty`/`hints`. Or pass `initial_question` to
  `/api/start`. The `skill` tag is a free-form id — a new tag starts a fresh
  per-skill belief. User rows are private by default (guests create public
  rows); generated follow-ups link via `parent_task_id`/`mvp_target_node_id`.
- **Change the model**: set `EVAL_MODEL` in `.env` (e.g. `gemini-3.5-flash-lite`).

## Environment variables

```bash
GOOGLE_API_KEY=...              # Required
EVAL_MODEL=gemini-3.5-flash-lite   # Judge/coach + decomposition model
EVAL_RETRY_ATTEMPTS=5           # Retry attempts (all layers)
EVAL_RETRY_INITIAL_DELAY=1.0    # Initial backoff (seconds)
EVAL_RETRY_MAX_DELAY=30.0       # Max backoff (seconds)
LEARNING_PARTNER_DB_URL=sqlite:///data/coach.db  # learner tables (optional; defaults to coach.db)
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