# AI Research Coach — AGENTS.md

## Quick Start

```bash
# From repo root
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Check env & model connectivity
python check_env.py

# ADK web UI (run from project root)
adk web --port 8000
# Open http://localhost:8000 → select "ai_research_coach"

# Or run custom FastAPI + Vite frontend
./run.sh
# Backend:  http://localhost:8001
# Frontend: http://localhost:5173
```

## Key Commands

| Task | Command |
|------|---------|
| Install deps | `pip install -r requirements.txt` |
| Test backend | `.venv/bin/python -m pytest` |
| Lint frontend | `cd frontend && npm run lint` |
| Typecheck frontend | `cd frontend && npx tsc -b` |
| Test frontend | `cd frontend && npm test` |
| Build frontend | `cd frontend && npm run build` |
| Run custom UI | `./run.sh` |
| ADK CLI | `adk run app` (from project root) |
| Env check | `python check_env.py` |

## Architecture Essentials

- **Entry point**: `app/agent.py` defines `root_agent` (ADK Agent with 5 tools)
- **Config-driven**: Skills/tasks in `config/skills.yaml` and `config/tasks.yaml` — no code changes to extend
- **Adaptive picker**: `core/picker.py` selects the next question to maximize expected information gain (Bayesian posterior variance reduction) per unit of expected time, weighted by skill importance and coverage
- **Bayesian scoring**: `core/score.py` keeps a Gaussian belief `N(mean, variance)` per skill; the judge's raw score is discounted by viewed hints before the conjugate update
- **Hints**: `core/hints.py` — tasks declare ordered hints; weak candidates get them pre-revealed, others request them on demand; viewed hints reduce effective mastery
- **Code eval**: `evaluators/judge.py` evaluates candidate code via a single structured LLM call (score + rationale + coaching response)
- **Coaching**: The judge's coaching response (in `evaluators/base.py` as `CoachContent`) identifies the candidate's misconception/gap and walks them step-by-step to the correct solution with code examples — no separate feedback step
- **Teaching pause**: After a submit the UI/agent does **not** auto-advance. The coaching response is shown and the candidate advances manually (`Next question`); the picked task is held in `pendingTask` on the frontend until then
- **Persistence**: SQLite at `data/coach.db` (gitignored)
- **Models**: `EVAL_CONV_MODEL` (agent) and `EVAL_MODEL` (judge/feedback) default to `gemini-3.5-flash-lite`

## Extending Without Code Changes

- **Add question**: Append to `config/tasks.yaml` with unique `id`, `skill`, and `prompt` (+ optional `hints` and `expected_time_min`)
- **Add skill**: Add a block in `config/skills.yaml` (id, name, description, importance), then tag tasks with that `skill`
- **Change model**: Set `EVAL_CONV_MODEL` or `EVAL_MODEL` in `.env`

## Task Types & Required Fields

| Mode | Required | Scoring |
|------|----------|---------|
| `code` (function) | `prompt` | LLM judge returns score (0..max_score) + rationale + coaching (misconception + steps) |
| `code` (scaffold) | `scaffold`, `prompt` | LLM judge returns score (0..max_score) + rationale + coaching (misconception + steps) |

Optional per task: `hints` (ordered list with `id`, `text`, `weight` 0..1, and `reveal_threshold` ability below which the engine pre-reveals it) and `expected_time_min` (overrides the difficulty-based time prior).

## Scoring / Adaptive Behavior

- Skill ability is a Gaussian belief (`N(mean, variance)`). The mean is the reported skill score; `1 - σ/σ_max` is the reported confidence.
- Effective score = `raw_fraction − Σ weight(viewed hints)`, clamped to [0, 1] — solving correctly with many hints yields lower mastery.
- `next_task` maximizes `EIG · importance · coverage / expected_time`, so it drills into informative, important, uncovered skills with cheap questions. It stops once all important skills are pinned (`variance < 0.01`) after the minimum question count, or when the task bank is exhausted.
- After a submit, the picked task is returned as `next_task` but held back by the UI (in `pendingTask`) until the candidate reviews the coaching and clicks **Next question** — the system never auto-advances. A `next_task: null` after the last question means the candidate is done; the frontend then shows the report button.

## Learning-Partner MVP Integration

- The `learning_partner` MVP lives in-repo as the `core.learning_partner` package (no editable install; `requirements.txt` just pins its deps `SQLAlchemy`/`alembic`/`pydantic`).
- `core/learner_bridge.py` (`LearnerBridge`) is the single facade: `ensure_learner(candidate)`, `bootstrap_task(task)`, `record_submission(candidate, task, result, coach, viewed)`, `learner_snapshot(candidate)`.
- `core/task_decomposer.py` decomposes a task/interview question into knowledge nodes+edges+primary via an LLM; falls back to a deterministic skill+problem graph when no `GOOGLE_API_KEY` (keeps tests and startup hermetic).
- Hooks: `/start` and ADK `start_assessment` call `ensure_learner` + `bootstrap_task`; `/submit` and ADK `submit_answer` call `record_submission`; `/report` attaches a `learner` block via `learner_snapshot`.
- The MVP and the parent share one SQLite DB (`data/coach.db`): the parent's `assessments`/`learner_bindings`/auth tables (raw `sqlite3`) coexist with the MVP's 13 SQLAlchemy tables in the same file. Override the MVP file with `LEARNING_PARTNER_DB_URL` if needed. The DB is gitignored.
- The MVP is LLM-free; all LLM work stays in the parent app. The parent's Bayesian `SkillState` scoring is untouched; the MVP runs in parallel.
- `core.learning_partner` is importable from the repo root (it is a sub-package of `core`), so no install step is needed.
- CLI inspector: `python -m core.learner_bridge --demo` (canned learner, no API key) or `python -m core.learner_bridge <candidate>` to print states/frontier/misconceptions/next action. The integration is backend-only (no UI surface).

## Environment Variables

```bash
GOOGLE_API_KEY=...              # Required
EVAL_MODEL=gemini-3.5-flash-lite   # Feedback model
EVAL_CONV_MODEL=gemini-3.5-flash-lite  # Conversation model
EVAL_RETRY_ATTEMPTS=5           # Retry attempts (all layers)
EVAL_RETRY_INITIAL_DELAY=1.0    # Initial backoff (seconds)
EVAL_RETRY_MAX_DELAY=30.0       # Max backoff (seconds)
LEARNING_PARTNER_DB_URL=sqlite:///data/coach.db  # MVP tables (optional; defaults to coach.db)
```

## Retry / Resilience

- All model calls use exponential backoff (5 attempts, 1s→30s, jitter) on 408/429/5xx
- Tools are idempotent: `submit_answer` returns stored result (+ stored coaching) if already scored; `start_assessment` resumes in-progress session

## Frontend Notes

- React 19 + TypeScript + Vite + Tailwind v4
- Chat-style UI: `ChatView`/`WelcomeView` in `frontend/src/components/Chat/` render the assessment as coach/user bubbles; the active task embeds Monaco via `CodeEditor`; submitted results render the judge's coaching (`CoachingBubble`: misconception + numbered steps with code examples)
- Guest mode = no account → practice (unscored; `/api/practice/submit` returns judge feedback without recording). Logged-in users (bearer token in `localStorage`) get scored assessments + per-account history
- Auth backend: `backend/auth.py` (bearer tokens, `get_current_user` FastAPI dependency) + `backend/google_auth.py` (Google OAuth authorization-code flow, stdlib only). Login is Google-only — `/auth/google/url` + `/auth/google/callback` exchange a code for a local user (keyed by email) and redirect to `FRONTEND_URL/?token=...`. Requires `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env`. Enforcement lives in `backend/routes.py` (`/start` returns 401 for anonymous `assessment` mode)
- Linting: `oxlint` (config in `frontend/.oxlintrc.json`)
- Typecheck: `tsc -b` (project references: `tsconfig.app.json`, `tsconfig.node.json`)
- Tests: Node's built-in `node:test` runner via type stripping (`npm test` in `frontend/`), zero extra deps; `tests/resolver.mjs` is a tiny loader that resolves the app's extensionless imports
- Service worker: `frontend/public/sw.js` caches assets cache-first for offline PWA; bump `CACHE_VERSION` when shipping a new prod build or browsers keep serving the stale bundle
- State: Zustand store (`frontend/src/stores/assessmentStore.ts`)

## Dependencies

- **Prefer zero new dependencies.** Exhaust all options using existing packages, transitive deps, or hand-rolled solutions before adding a new one.
- **Check transitive deps first.** Run `npm ls <pkg>` or `pip show <pkg>` to see if a needed library is already available indirectly (e.g. `highlight.js` via `rehype-highlight`).
- **If a new dep is unavoidable, ask the user to choose** between the candidate options (include trade-offs: bundle size, maintenance status, API surface).
- Never add a dependency for a single small feature that can be implemented in a few lines of code.

## Gotchas

- `.venv` is the virtualenv; `run.sh` uses `.venv/bin/uvicorn` directly
- `data/` directory is gitignored; SQLite DB created on first assessment
- The `.env` file contains a real API key — do not commit changes to it
