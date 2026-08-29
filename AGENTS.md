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
- **Code eval**: `evaluators/judge.py` evaluates candidate code via a single structured LLM call (score + rationale + feedback)
- **Feedback**: Integrated into the judge call — no separate feedback step
- **Persistence**: SQLite at `data/coach.db` (gitignored)
- **Models**: `EVAL_CONV_MODEL` (agent) and `EVAL_MODEL` (judge/feedback) default to `gemini-3.5-flash-lite`

## Extending Without Code Changes

- **Add question**: Append to `config/tasks.yaml` with unique `id`, `skill`, and `prompt` (+ optional `hints` and `expected_time_min`)
- **Add skill**: Add a block in `config/skills.yaml` (id, name, description, importance), then tag tasks with that `skill`
- **Change model**: Set `EVAL_CONV_MODEL` or `EVAL_MODEL` in `.env`
- **Change time budget**: set `max_time_min` in `config/skills.yaml`

## Task Types & Required Fields

| Mode | Required | Scoring |
|------|----------|---------|
| `code` (function) | `prompt` | LLM judge returns score (0..max_score) + rationale + feedback |
| `code` (scaffold) | `scaffold`, `prompt` | LLM judge returns score (0..max_score) + rationale + feedback |

Optional per task: `hints` (ordered list with `id`, `text`, `weight` 0..1, and `reveal_threshold` ability below which the engine pre-reveals it) and `expected_time_min` (overrides the difficulty-based time prior).

## Scoring / Adaptive Behavior

- Skill ability is a Gaussian belief (`N(mean, variance)`). The mean is the reported skill score; `1 - σ/σ_max` is the reported confidence.
- Effective score = `raw_fraction − Σ weight(viewed hints)`, clamped to [0, 1] — solving correctly with many hints yields lower mastery.
- `next_task` maximizes `EIG · importance · coverage / expected_time`, so it drills into informative, important, uncovered skills with cheap questions. It stops at max questions, the assessment time budget (`max_time_min`), or once all important skills are pinned (`variance < 0.01`) after the minimum question count.

## Environment Variables

```bash
GOOGLE_API_KEY=...              # Required
EVAL_MODEL=gemini-3.5-flash-lite   # Feedback model
EVAL_CONV_MODEL=gemini-3.5-flash-lite  # Conversation model
EVAL_RETRY_ATTEMPTS=5           # Retry attempts (all layers)
EVAL_RETRY_INITIAL_DELAY=1.0    # Initial backoff (seconds)
EVAL_RETRY_MAX_DELAY=30.0       # Max backoff (seconds)
```

## Retry / Resilience

- All model calls use exponential backoff (5 attempts, 1s→30s, jitter) on 408/429/5xx
- Tools are idempotent: `submit_answer` returns stored result if already scored; `start_assessment` resumes in-progress session

## Frontend Notes

- React 19 + TypeScript + Vite + Tailwind v4
- Linting: `oxlint` (config in `frontend/.oxlintrc.json`)
- Typecheck: `tsc -b` (project references: `tsconfig.app.json`, `tsconfig.node.json`)
- Tests: Node's built-in `node:test` runner via type stripping (`npm test` in `frontend/`), zero extra deps
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
