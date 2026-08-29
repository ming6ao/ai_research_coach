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
| Lint frontend | `cd frontend && npm run lint` |
| Typecheck frontend | `cd frontend && npx tsc -b` |
| Build frontend | `cd frontend && npm run build` |
| Run custom UI | `./run.sh` |
| ADK CLI | `adk run app` (from project root) |
| Env check | `python check_env.py` |

## Architecture Essentials

- **Entry point**: `app/agent.py` defines `root_agent` (ADK Agent with 4 tools)
- **Config-driven**: Roles/tasks in `config/roles.yaml` and `config/tasks.yaml` — no code changes to extend
- **Code eval**: `evaluators/judge.py` evaluates candidate code via a single structured LLM call (score + rationale + feedback)
- **Feedback**: Integrated into the judge call — no separate feedback step
- **Persistence**: SQLite at `data/coach.db` (gitignored)
- **Models**: `EVAL_CONV_MODEL` (agent) and `EVAL_MODEL` (judge/feedback) default to `gemini-3.5-flash-lite`

## Extending Without Code Changes

- **Add question**: Append to `config/tasks.yaml` with unique `id`, `role`, `skill`, and `prompt`
- **Add skill**: Add under role in `config/roles.yaml`
- **Add role**: New block in `config/roles.yaml`, then tag tasks with that `role`
- **Change model**: Set `EVAL_CONV_MODEL` or `EVAL_MODEL` in `.env`

## Task Types & Required Fields

| Mode | Required | Scoring |
|------|----------|---------|
| `code` (function) | `prompt` | LLM judge returns score (0..max_score) + rationale + feedback |
| `code` (scaffold) | `scaffold`, `prompt` | LLM judge returns score (0..max_score) + rationale + feedback |

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
