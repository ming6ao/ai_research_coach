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
| Reset activity/progress (keeps users/auth + task bank; admin UI "Reset activity" button or `POST /admin/reset`) | via the admin UI or API — no CLI |
| Lint frontend | `cd frontend && npm run lint` |
| Typecheck frontend | `cd frontend && npx tsc -b` |
| Test frontend | `cd frontend && npm test` |
| Build frontend | `cd frontend && npm run build` |
| Run custom UI | `./run.sh` |
| Env check | `python check_env.py` |

## Architecture Essentials

- **Entry point**: FastAPI app in `backend/main.py` (`backend/v1/*` resources + `backend/auth_routes.py` + admin routes). No ADK agent.
- **Database is the source of truth for tasks**: the `tasks` table is the only question bank — there is no code catalog. Tasks are authored in the DB via `POST /api/v1/tasks`, the curator UI ("My questions"), or the admin "Add question" form (`POST /admin/seeds`). `create_schema()` (startup) creates/migrates tables but never writes tasks; `reset_database()` (`POST /admin/reset`, admin UI "Reset activity") wipes activity/progress (`session_steps`, `user_skill_beliefs`, `active_sessions`, `trajectory_shares`) while preserving users/auth **and the task bank**. Tasks are code blocks with per-part `parts: [{key, prompt, tags, max_score, difficulty}]` and may be linked into version chains via `depends_on_task_id`/`version_root_id` (`version_index`); a successor modifies the predecessor's code. Existing `source='seed'` rows from before this change are ordinary DB-managed tasks like any other.
- **Tag everything**: every task — user, admin, or generated — carries `tags: {primary: <fine tag>, secondary: [0-2 fine tags]}` + `task_type` (`implement|apply|debug|design|analyze`); every part carries its own tags too. `coach/taxonomy.py` is the single source of truth (11 families / 46 fine tags, `ALIASES`, `validate`, `family_of`); unknown tags are rejected (422). Only primary tags (block or part) feed the belief system; secondary tags count for coverage/diversity only.
- **Hierarchical mastery**: `coach/score.py` (global) + `coach/area_score.py` (family + tag) keep per-level sufficient statistics. At read time `area_report_dict` folds them with empirical-Bayes shrinkage (`eta=2.0`, weight `n/(n+eta)` on own evidence, parent = family's/global's shrunk estimate) — order-invariant, sparse tags report ~family estimate, dense tags converge to own evidence.
- **Hybrid question selection**: `coach/selection.py:pick_next_task` — (1) pending generated task, (2) **version successor** (`_version_successor`: the unasked task whose `depends_on_task_id` == last answered id; its view carries the predecessor's submitted code as `previous_code`), (3) judge-driven follow-up (`coach/remediation.py`: a simpler task drilled from the judge's misconception/feedback text, difficulty tuned to ~80% P(solve) via `coach/solvability.py`), (4) EIG bank picker with small exploration bonuses (`coach/picker.py`: `0.004·1/(1+family_attempts) + 0.001·1/(1+tag_attempts)`, minus a soft `-0.010` same-family penalty; non-root versions are excluded from the bank), (5) scope-widening challenge (least-covered family/tag). An optional `family` param restricts the bank branch to one family (used to seed a session with a random question in an area); a `sample_top_n` picks uniformly among the top-N EIG candidates
- **No knowledge graph**: there are no nodes/edges. Each task carries `context_notes` (2–4 plain-English sentences), generated once at creation by a combined LLM call (`coach/task_decomposer.py:describe_and_categorize` returns notes + tags in one call) and editable via `PATCH /api/v1/tasks/{id}` (owner or admin)
- **Code blocks & version chains**: a task's `parts` are scored **per part** by the judge (`coach/judge.py` returns `parts: [{key, score, rationale}]`; aggregate = sum). A single submission fills the whole block; each part's primary tag updates the belief system at the part's own difficulty, and the global belief updates once with the aggregate fraction. A version successor modifies the same code and is judged against its own criteria with the predecessor's answer shown as `previous_code`. There are **no hints** (`coach/hints.py` was removed).
- **Code eval**: `coach/judge.py` evaluates candidate code via a single structured LLM call returning per-part scores + rationale + coaching response; `score_targets()` treats a partless task as one implicit part
- **Coaching**: The judge's coaching response (in `coach/judge.py` as `CoachContent`) identifies the candidate's misconception/gap and walks them step-by-step to the correct solution with code examples — no separate feedback step
- **Teaching pause**: After a submit the UI does **not** auto-advance. The coaching response is shown and the candidate advances manually (`Next question`); the picked task is held until then
- **No summative product**: there is no `assessments` table, report, verdict, or raw-score UI. The app probes and teaches; the merged home page shows overall + per-family confidence bars and per-tag chips (from the `mastery` block in answers/completion/resume/overview responses) and past sessions are reviewed from the Recent-sessions list
- **Persistence**: single SQLite file `data/coach.db` (gitignored) with 8 tables (`users`, `auth_tokens`, `active_sessions`, `oauth_states`, `tasks`, `session_steps`, `user_skill_beliefs`, `trajectory_shares`). `coach/db.py` is the single connection module; `create_schema()` drops removed columns/tables (incl. `hints_json`/`cluster_id`/`followups_json`), adds `parts_json`/`version_index`/`depends_on_task_id`/`version_root_id`, migrates beliefs to one row per `(candidate, level, key)` (`level` ∈ global/family/tag) with a unique index (`uq_user_skill_beliefs`), and backfills `session_steps` from legacy JSON blobs. `session_steps` (`coach/steps.py`) holds one RL-shaped row per scored answer (`hints_used` column kept for legacy; callers pass `[]`; `answer_for_task` fetches a task's submitted code); `trajectory_shares` (`coach/shares.py`) stores anonymous Copy-on-Write share snapshots for resume. Candidate identity is resolved by `backend/dependencies.py:resolve_candidate` (signed-in email or stable `X-Guest-Id` per browser)
- **Models**: `EVAL_MODEL` (judge/coach + decomposition) defaults to `gemini-3.5-flash-lite`

## Extending Without Code Changes

- **Add question**: `POST /api/v1/tasks` with `prompt`, optional `scaffold`/`difficulty`/`parts`/`tags`/`task_type`/version fields; or `initial_question` on `POST /api/v1/sessions` (auto-tagged by one combined LLM call); or seed a session with a random question in one area via `family` on `POST /api/v1/sessions`
- **Change model**: Set `EVAL_MODEL` in `.env`

## Task Types & Required Fields

| Mode | Required | Scoring |
|------|----------|---------|
| `code` (function) | `prompt` | LLM judge returns per-part score (0..max) + rationale + coaching (misconception + steps) |
| `code` (scaffold) | `scaffold`, `prompt` | LLM judge returns per-part score (0..max) + rationale + coaching (misconception + steps) |
| `code` (block) | `parts: [{key, prompt, tags, max_score, difficulty}]` (+ task-level `prompt`/`scaffold`) | LLM judge returns one score per part; aggregate = sum |

Every task carries `tags: {primary, secondary[]}` (fine tags from `coach/taxonomy.py`; unknown → 422) and a `task_type`. Code blocks additionally carry per-part `tags`. Optional version fields: `version_index`, `depends_on_task_id`, `version_root_id` (a successor builds on the predecessor's submitted code).

## Scoring / Adaptive Behavior

- Overall ability is a Gaussian belief (`N(mean, variance)`). The mean is the reported score; `1 - σ/σ_max` is the reported confidence.
- Family/tag beliefs are the same Gaussian over each level's own observations, shrunk at read time toward the parent level (`eta=2.0`): an unattempted tag reports its family's estimate, sparse tags lean on the family, dense tags converge to the candidate's own evidence. Only primary tags (block or part) update the estimator.
- A block submission updates each part's primary tag and family at that part's own difficulty; the global ability updates once with the aggregate fraction. Effective score = `raw_fraction`, clamped to [0, 1] (no hint penalty).
- The bank picker maximizes `EIG / expected_time` (expected time scales with the number of parts) plus small exploration bonuses for under-asked families/tags (`0.004`/`0.001` · `1/(1+attempts)`), minus a soft `-0.010` penalty for repeating the previous family. Version successors are never bank candidates. The session ends when the task bank is exhausted.
- After a submit, the picked task is returned as `next_task` but held back by the UI until the candidate reviews the coaching and clicks **Next question** — the system never auto-advances. A `next_task: null` after the last question means the candidate is done; the frontend then returns to the merged home page, which shows the candidate's persisted progress (via `GET /api/v1/me/overview`).

## Learner Model (hierarchical beliefs)

- There is no `learner/` package, no nodes/edges, no frontier/policy.
- Mastery is three Gaussian layers per candidate — `tag ← family ← global` — stored as one `user_skill_beliefs` row per `(candidate, level, key)` and folded to reported scores at read time (`coach/area_score.py:area_report_dict`).
- Follow-ups are judge-driven: `coach/remediation.py` drills the judge's gap text; generated tasks inherit the root task's tags.
- `coach/task_decomposer.py` has two LLM helpers with deterministic no-API-key fallbacks: `describe_and_categorize` (combined context notes + tags) and `generate_followup_task` (simpler drill).

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
- Chat-style UI: `ChatView` in `frontend/src/components/Chat/` renders the session as coach/user bubbles; the active task embeds Monaco via `CodeEditor` (initialized from `previous_code ?? scaffold`); the prompt bubble lists each part's question for code blocks; submitted results render the judge's coaching (`CoachingBubble`: verdict chip + misconception + numbered steps with code examples). There are no hints
- Merged home page: `frontend/src/components/Home/HomeView.tsx` is the landing/progress page in one — greeting, the question `Composer`, a `Start a new session` button (replaces the old "Random question"), overall confidence + per-family mastery bars (each area card is **clickable** and starts a session seeded with a random question in that family via `{family}`), expandable per-tag chips, and the Recent-sessions list. It loads its snapshot from `GET /api/v1/me/overview`. There is no separate progress screen; finishing a session returns here (beliefs persist server-side), and past sessions are reviewed by opening them from Recent sessions (full chat history with coaching)
- Single unified behavior for guests and signed-in users (no practice/assessment split). Guests keep a stable per-browser anonymous identity (`ai_coach_guest_id` in `localStorage`, sent as the `X-Guest-Id` header when no Bearer token is present) so mastery + session history persist across sessions/reloads; signed-in users (bearer token in `localStorage`) are keyed by email and get per-account history
- Progress/memory: `GET /api/v1/me/overview` (optional auth) returns `{candidate, ability, mastery, sessions}` from `user_skill_beliefs`; `GET /api/v1/me/sessions` lists sessions for guests too; `DELETE /api/v1/me/data` wipes either identity
- Task bubbles show tag chips
- Curator UI: `frontend/src/components/Curator/` — any signed-in user can author/manage their own questions via "My questions" in the header (`CuratorView` list + `TaskEditor` with a learner-view `TaskPreview`). New questions default public (toggleable `is_public`); `GET /api/v1/me/tasks` lists the owner's tasks with attempt counts, and `GET /api/v1/taxonomy` (public, unlike `/admin/taxonomy`) feeds the tag dropdowns. Admins enter the same editor for any task via the "Curator editor" button in the admin task `DetailPane` (owner-or-admin guard reused)
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