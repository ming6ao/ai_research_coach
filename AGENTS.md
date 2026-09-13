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
| Seed the builtin question bank (idempotent, runs at startup) | `python -m coach.seed_bank` |
| Mint tasks for uncovered/low-coverage tags (LLM) | `python -m coach.seed_bank --fill-gaps [--limit N]` |
| Lint frontend | `cd frontend && npm run lint` |
| Typecheck frontend | `cd frontend && npx tsc -b` |
| Test frontend | `cd frontend && npm test` |
| Build frontend | `cd frontend && npm run build` |
| Run custom UI | `./run.sh` |
| Env check | `python check_env.py` |

## Architecture Essentials

- **Entry point**: FastAPI app in `backend/main.py` (`backend/v1/*` resources + `backend/auth_routes.py` + admin routes). No ADK agent.
- **Builtin question bank**: `coach/seed_bank.py` ships a curated ~30-task code catalog (`SEED_CATALOG`, all `context_notes` pre-authored) covering every family and fine tag. `seed_question_bank()` runs from `create_schema()` (startup), is hermetic (no LLM/network), and uses a single batched `INSERT OR IGNORE` — re-runs are no-ops and human-edited seeds are never overwritten. `coverage_report()` (admin UI) + `--fill-gaps` mint tasks for uncovered/lowest-coverage tags as `source="seed_llm"`.
- **Tag everything**: every task — seed, user, or generated — carries `tags: {primary: <fine tag>, secondary: [0-2 fine tags]}` + `task_type` (`implement|apply|debug|design|analyze`). `coach/taxonomy.py` is the single source of truth (11 families / 46 fine tags, `ALIASES`, `validate`, `family_of`); unknown tags are rejected (422). Only the primary tag feeds the belief system; secondary tags count for coverage/diversity only.
- **Hierarchical mastery**: `coach/score.py` (global) + `coach/area_score.py` (family + tag) keep per-level sufficient statistics. At read time `area_report_dict` folds them with empirical-Bayes shrinkage (`eta=2.0`, weight `n/(n+eta)` on own evidence, parent = family's/global's shrunk estimate) — order-invariant, sparse tags report ~family estimate, dense tags converge to own evidence.
- **Hybrid question selection**: `coach/selection.py:pick_next_task` — (1) pending generated task, (2) judge-driven follow-up (`coach/remediation.py`: a simpler task drilled from the judge's misconception/feedback text, difficulty tuned to ~80% P(solve) via `coach/solvability.py`), (3) EIG bank picker with small exploration bonuses (`coach/picker.py`: `0.004·1/(1+family_attempts) + 0.001·1/(1+tag_attempts)`, minus a soft `-0.010` same-family penalty), (4) scope-widening challenge (least-covered family/tag). An optional `family` param restricts the bank branch to one family (used to seed a session with a random question in an area); a `sample_top_n` picks uniformly among the top-N EIG candidates
- **No knowledge graph**: there are no nodes/edges. Each task carries `context_notes` (2–4 plain-English sentences), generated once at creation by a combined LLM call (`coach/task_decomposer.py:describe_and_categorize` returns notes + tags in one call) and editable via `PATCH /api/v1/tasks/{id}` (owner or admin)
- **Hints**: `coach/hints.py` — tasks declare ordered hints; weak candidates get them pre-revealed, others request them on demand; viewed hints reduce effective mastery
- **Code eval**: `coach/judge.py` evaluates candidate code via a single structured LLM call (score + rationale + coaching response)
- **Coaching**: The judge's coaching response (in `coach/judge.py` as `CoachContent`) identifies the candidate's misconception/gap and walks them step-by-step to the correct solution with code examples — no separate feedback step
- **Teaching pause**: After a submit the UI does **not** auto-advance. The coaching response is shown and the candidate advances manually (`Next question`); the picked task is held until then
- **No summative product**: there is no `assessments` table, report, verdict, or raw-score UI. The app probes and teaches; the merged home page shows overall + per-family confidence bars and per-tag chips (from the `mastery` block in answers/completion/resume/overview responses) and past sessions are reviewed from the Recent-sessions list
- **Persistence**: single SQLite file `data/coach.db` (gitignored) with 8 tables (`users`, `auth_tokens`, `active_sessions`, `oauth_states`, `tasks`, `session_steps`, `user_skill_beliefs`, `trajectory_shares`). `coach/db.py` is the single connection module; `create_schema()` drops removed columns/tables, seeds the question bank, migrates beliefs to one row per `(candidate, level, key)` (`level` ∈ global/family/tag) with a unique index (`uq_user_skill_beliefs`), and backfills `session_steps` from legacy JSON blobs. `session_steps` (`coach/steps.py`) holds one RL-shaped row per scored answer (replacing the old `task_attempts` table and `feedback_json` blob); `trajectory_shares` (`coach/shares.py`) stores anonymous Copy-on-Write share snapshots for resume. Candidate identity is resolved by `backend/dependencies.py:resolve_candidate` (signed-in email or stable `X-Guest-Id` per browser)
- **Models**: `EVAL_MODEL` (judge/coach + decomposition) defaults to `gemini-3.5-flash-lite`

## Extending Without Code Changes

- **Add question**: `POST /api/v1/tasks` with `prompt`, optional `scaffold`/`difficulty`/`hints`/`tags`/`task_type`; or `initial_question` on `POST /api/v1/sessions` (auto-tagged by one combined LLM call); or seed a session with a random question in one area via `family` on `POST /api/v1/sessions`
- **Change model**: Set `EVAL_MODEL` in `.env`

## Task Types & Required Fields

| Mode | Required | Scoring |
|------|----------|---------|
| `code` (function) | `prompt` | LLM judge returns score (0..max_score) + rationale + coaching (misconception + steps) |
| `code` (scaffold) | `scaffold`, `prompt` | LLM judge returns score (0..max_score) + rationale + coaching (misconception + steps) |

Every task carries `tags: {primary, secondary[]}` (fine tags from `coach/taxonomy.py`; unknown → 422) and a `task_type`. Optional per task: `hints` (ordered list with `id`, `text`, `weight` 0..1, and `reveal_threshold` ability below which the engine pre-reveals it).

## Scoring / Adaptive Behavior

- Overall ability is a Gaussian belief (`N(mean, variance)`). The mean is the reported score; `1 - σ/σ_max` is the reported confidence.
- Family/tag beliefs are the same Gaussian over each level's own observations, shrunk at read time toward the parent level (`eta=2.0`): an unattempted tag reports its family's estimate, sparse tags lean on the family, dense tags converge to the candidate's own evidence. Only the primary tag updates the estimator.
- Effective score = `raw_fraction − Σ weight(viewed hints)`, clamped to [0, 1] — solving correctly with many hints yields lower mastery.
- The bank picker maximizes `EIG / expected_time` plus small exploration bonuses for under-asked families/tags (`0.004`/`0.001` · `1/(1+attempts)`), minus a soft `-0.010` penalty for repeating the previous family. The session ends when the task bank is exhausted.
- After a submit, the picked task is returned as `next_task` but held back by the UI until the candidate reviews the coaching and clicks **Next question** — the system never auto-advances. A `next_task: null` after the last question means the candidate is done; the frontend then returns to the merged home page, which shows the candidate's persisted progress (via `GET /api/v1/me/overview`).

## Learner Model (hierarchical beliefs)

- There is no `learner/` package, no nodes/edges, no frontier/policy.
- Mastery is three Gaussian layers per candidate — `tag ← family ← global` — stored as one `user_skill_beliefs` row per `(candidate, level, key)` and folded to reported scores at read time (`coach/area_score.py:area_report_dict`).
- Follow-ups are judge-driven: `coach/remediation.py` drills the judge's gap text; generated tasks inherit the root task's tags.
- `coach/task_decomposer.py` has three LLM helpers with deterministic no-API-key fallbacks: `describe_and_categorize` (combined context notes + tags), `generate_followup_task` (simpler drill), and `generate_seed_task_for_tag` (`--fill-gaps`).

## Environment Variables

```bash
GOOGLE_API_KEY=...              # Required
EVAL_MODEL=gemini-3.5-flash-lite   # Judge/coach + decomposition model
EVAL_RETRY_ATTEMPTS=5           # Retry attempts (all layers)
EVAL_RETRY_INITIAL_DELAY=1.0    # Initial backoff (seconds)
EVAL_RETRY_MAX_DELAY=30.0       # Max backoff (seconds)
```

## Retry / Resilience

- All model calls use exponential backoff (5 attempts, 1s→30s, jitter) on 408/429/5xx
- `POST /api/v1/sessions/{id}/answers` is idempotent: it returns the stored result (+ stored coaching, `already_answered: true`) if the task was already scored; `POST /api/v1/sessions` starts and `GET /api/v1/sessions/{id}` resumes sessions

## Frontend Notes

- React 19 + TypeScript + Vite + Tailwind v4
- Chat-style UI: `ChatView` in `frontend/src/components/Chat/` renders the session as coach/user bubbles; the active task embeds Monaco via `CodeEditor`; submitted results render the judge's coaching (`CoachingBubble`: verdict chip + misconception + numbered steps with code examples)
- Merged home page: `frontend/src/components/Home/HomeView.tsx` is the landing/progress page in one — greeting, the question `Composer`, a `Start a new session` button (replaces the old "Random question"), overall confidence + per-family mastery bars (each area card is **clickable** and starts a session seeded with a random question in that family via `{family}`), expandable per-tag chips, and the Recent-sessions list. It loads its snapshot from `GET /api/v1/me/overview`. There is no separate progress screen; finishing a session returns here (beliefs persist server-side), and past sessions are reviewed by opening them from Recent sessions (full chat history with coaching)
- Single unified behavior for guests and signed-in users (no practice/assessment split). Guests keep a stable per-browser anonymous identity (`ai_coach_guest_id` in `localStorage`, sent as the `X-Guest-Id` header when no Bearer token is present) so mastery + session history persist across sessions/reloads; signed-in users (bearer token in `localStorage`) are keyed by email and get per-account history
- Progress/memory: `GET /api/v1/me/overview` (optional auth) returns `{candidate, ability, mastery, sessions}` from `user_skill_beliefs`; `GET /api/v1/me/sessions` lists sessions for guests too; `DELETE /api/v1/me/data` wipes either identity
- Task bubbles show tag chips; the admin `coverage` tab shows the seed-bank coverage report
- Auth backend: `backend/auth.py` (session tokens: `Authorization: Bearer` header or HttpOnly `ai_coach_token` cookie, `require_user`/`get_current_user` FastAPI dependencies) + `backend/google_auth.py` (Google OAuth authorization-code flow, single-use DB-backed `state`). Login is Google-only — `/auth/google/url` + `/auth/google/callback` exchange a code for a local user (keyed by email), set the session cookie, and redirect (303) to `FRONTEND_URL/?login=success` (no token in the URL). Requires `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env`. Cookie-authenticated writes additionally require a matching `Origin`/`Referer` header (`backend/csrf.py`); Bearer callers are exempt
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