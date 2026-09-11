# AI Research Coach — AGENTS.md

## Quick Start

```bash
# From repo root
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Check env & model connectivity
python check_env.py

# Run the custom FastAPI + Vite frontend
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
| Env check | `python check_env.py` |

## Architecture Essentials

- **Entry point**: FastAPI app in `backend/main.py` (`backend/routes.py` + admin routes). No ADK agent.
- **Config-driven**: Questions in `config/tasks.yaml` — no code changes to extend; each task's `skill` tag is a free-form id that keys a per-skill belief
- **Bayesian probing**: `coach/score.py` + `coach/picker.py` keep a Gaussian belief `N(mean, variance)` per skill; `pick_next_task` (in `learner/engine.py`) selects questions to maximize expected information gain (EIG) per unit of expected time, weighted by skill coverage
- **Hybrid question selection**: `learner/engine.py:pick_next_task` — (1) pending generated remediation task, (2) frontier-driven remediation (`coach/remediation.py` + knowledge-graph learner model), (3) EIG bank picker, (4) `None` when done
- **Learner model**: the flat `learner/` package (one module per topic: `engine`, `graph`, `states`, `evidence`, `assessment`, `update`, `misconception`, `frontier`, `policy`, `orchestrator`, `traversal`) keeps per-node mastery/uncertainty beliefs that drive the frontier/policy/remediation math
- **Hints**: `coach/hints.py` — tasks declare ordered hints; weak candidates get them pre-revealed, others request them on demand; viewed hints reduce effective mastery
- **Code eval**: `coach/judge.py` evaluates candidate code via a single structured LLM call (score + rationale + coaching response)
- **Coaching**: The judge's coaching response (in `coach/judge.py` as `CoachContent`) identifies the candidate's misconception/gap and walks them step-by-step to the correct solution with code examples — no separate feedback step
- **Teaching pause**: After a submit the UI does **not** auto-advance. The coaching response is shown and the candidate advances manually (`Next question`); the picked task is held until then
- **No summative product**: there is no `assessments` table, report, verdict, or raw-score UI. The app probes and teaches; the progress view shows per-skill confidence + per-node status/misconceptions/next actions
- **Persistence**: single SQLite file `data/coach.db` (gitignored) with 12 tables (`users`, `auth_tokens`, `active_sessions`, `knowledge_nodes`, `knowledge_edges`, `learners`, `learner_knowledge_states`, `evidence`, `assessment_tasks`, `assessment_targets`, `learner_misconceptions`, `learner_frontier`). `coach/db.py` is the single connection module
- **Models**: `EVAL_MODEL` (judge/coach + decomposer) defaults to `gemini-3.5-flash-lite`

## Extending Without Code Changes

- **Add question**: Append to `config/tasks.yaml` with unique `id`, `skill`, and `prompt` (+ optional `hints` and `expected_time_min`)
- **Change model**: Set `EVAL_MODEL` in `.env`

## Task Types & Required Fields

| Mode | Required | Scoring |
|------|----------|---------|
| `code` (function) | `prompt` | LLM judge returns score (0..max_score) + rationale + coaching (misconception + steps) |
| `code` (scaffold) | `scaffold`, `prompt` | LLM judge returns score (0..max_score) + rationale + coaching (misconception + steps) |

Optional per task: `hints` (ordered list with `id`, `text`, `weight` 0..1, and `reveal_threshold` ability below which the engine pre-reveals it) and `expected_time_min` (overrides the difficulty-based time prior).

## Scoring / Adaptive Behavior

- Skill ability is a Gaussian belief (`N(mean, variance)`). The mean is the reported skill score; `1 - σ/σ_max` is the reported confidence.
- Effective score = `raw_fraction − Σ weight(viewed hints)`, clamped to [0, 1] — solving correctly with many hints yields lower mastery.
- The bank picker maximizes `EIG · coverage / expected_time`, so it drills into informative, uncovered skills with cheap questions. The session ends when the task bank is exhausted.
- After a submit, the picked task is returned as `next_task` but held back by the UI until the candidate reviews the coaching and clicks **Next question** — the system never auto-advances. A `next_task: null` after the last question means the candidate is done; the frontend then shows the progress view (via `/api/complete`).

## Learner Model (flat `learner/`)

- The learner package lives in-repo at `learner/` (one module per topic — models, services, and SQL persistence for that topic live together; SQLAlchemy `Base`/engine/converters live in `coach/db.py`). No install step needed.
- `learner/engine.py` (`LearnerEngine`) is the single facade: `ensure_learner(candidate)`, `bootstrap_task(task)`, `bootstrap_generated_task(task)`, `record_submission(candidate, task, result, coach, viewed)`, `learner_snapshot(candidate)`, plus the hybrid `pick_next_task` and `clear_learner_data(candidate)`.
- Candidate identity lives on the `learners.candidate` column (UNIQUE) — no separate binding table.
- `coach/task_decomposer.py` decomposes a task/interview question into knowledge nodes+edges+primary via an LLM; falls back to a deterministic skill+problem graph when no `GOOGLE_API_KEY` (keeps tests and startup hermetic).
- Hooks: `/api/start` and `/api/session/open` call `ensure_learner` + `bootstrap_task`; `/api/submit` calls `record_submission`; `/api/complete` and `/api/session/open` attach a `learner` block via `learner_snapshot`.
- The learner model is LLM-free; all LLM work lives in `coach/judge.py` and `coach/task_decomposer.py`. The parent's Bayesian `SkillState` scoring runs in parallel.
- CLI inspector: `python -m learner.engine --demo` (canned learner, no API key) or `python -m learner.engine <candidate>` to print states/frontier/misconceptions/next action. Backend-only (no UI surface).

## Environment Variables

```bash
GOOGLE_API_KEY=...              # Required
EVAL_MODEL=gemini-3.5-flash-lite   # Judge/coach + decomposition model
EVAL_RETRY_ATTEMPTS=5           # Retry attempts (all layers)
EVAL_RETRY_INITIAL_DELAY=1.0    # Initial backoff (seconds)
EVAL_RETRY_MAX_DELAY=30.0       # Max backoff (seconds)
LEARNING_PARTNER_DB_URL=sqlite:///data/coach.db  # learner tables (optional; defaults to coach.db)
```

## Retry / Resilience

- All model calls use exponential backoff (5 attempts, 1s→30s, jitter) on 408/429/5xx
- `/api/submit` is idempotent: it returns the stored result (+ stored coaching) if the task was already scored; `/api/start` and `/api/session/open` resume in-progress sessions

## Frontend Notes

- React 19 + TypeScript + Vite + Tailwind v4
- Chat-style UI: `ChatView`/`WelcomeView` in `frontend/src/components/Chat/` render the session as coach/user bubbles; the active task embeds Monaco via `CodeEditor`; submitted results render the judge's coaching (`CoachingBubble`: verdict chip + misconception + numbered steps with code examples)
- Single unified behavior for guests and signed-in users (no practice/assessment split). Guests keep their in-progress session in `localStorage`; signed-in users (bearer token in `localStorage`) get per-account history
- Progress view: `frontend/src/components/Progress/LearnerProgressView.tsx` shows per-skill confidence and per-node status + misconceptions + next actions after `/api/complete` or on resume of a done session
- Auth backend: `backend/auth.py` (bearer tokens, `get_current_user` FastAPI dependency) + `backend/google_auth.py` (Google OAuth authorization-code flow, stdlib only). Login is Google-only — `/auth/google/url` + `/auth/google/callback` exchange a code for a local user (keyed by email) and redirect to `FRONTEND_URL/?token=...`. Requires `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env`
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
- `data/` directory is gitignored; the SQLite DB is created on first run
- The `.env` file contains a real API key — do not commit changes to it