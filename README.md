# AI Research Coach

An evaluation agent built with the [Agent Development Kit (ADK)](https://adk.dev) that assesses a candidate's AI/ML coding skills against a unified skill tree — every candidate is evaluated the same way, with no role selection.

The design is data-driven: adding new questions or skills is done by editing config files — not code. It starts simple (CLI/web chat + local code runner) and is structured to scale into a sandboxed, adaptive, multi-candidate platform.

## Architecture

```
ai_research_coach/
├── app/
│   └── agent.py          # root_agent + 5 tools (orchestrator)
├── config/
│   ├── skills.yaml       # unified skill tree (importance, max_time_min)
│   └── tasks.yaml        # question/task bank (code only, with optional hints)
├── core/
│   ├── config.py         # paths + model selection
│   ├── session.py        # candidate session state (serialized into ADK state)
│   ├── picker.py         # next question: max information gain per unit time
│   ├── hints.py          # adaptive hint selection + hint penalty
│   ├── score.py          # Bayesian ability estimation (Gaussian belief)
│   ├── report.py         # skills profile + readiness verdict
│   └── storage.py        # SQLite persistence of finished assessments
└── evaluators/
    ├── base.py           # EvaluationResult + CoachContent (misconception + steps)
    └── judge.py          # LLM judge (score + rationale + coaching response)
```

### Evaluation flow

1. **Intake** — `start_assessment` loads the unified skill tree and the full task bank. Every candidate is evaluated the same way.
2. **Task loop** — the adaptive picker selects one coding task at a time to maximize expected information gain per unit time. The candidate writes code in an editor and may view hints (which reduce effective mastery). The LLM judge returns a score, rationale, and a **coaching response**.
3. **Teaching pause** — after a submit the system does **not** auto-advance to the next task. The judge's coaching response is shown instead: it identifies the candidate's specific misconception/gap ("where the gap is") and walks them **step by step** through the correct solution with explanations and code examples. The candidate reviews it and clicks **Next question** to continue.
4. **Report** — `get_report` aggregates per-skill scores into an overall score, a verdict (`Ready` / `Conditionally ready` / `Not ready`), a list of skill gaps (< 0.6 fraction), and persists the assessment to SQLite.

## Project structure & setup

This folder is an ADK agent project (it contains `app/agent.py` with a `root_agent`).

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> Running only on CPU (no CUDA GPU)? Install the CPU-only PyTorch instead:
> `pip install torch --index-url https://download.pytorch.org/whl/cpu`

### 3. Set your API key

Create a `.env` file in this directory with your Gemini API key:

```bash
echo 'GOOGLE_API_KEY="YOUR_API_KEY"' > .env
```

> Two models are used: **conversations** default to `gemini-3.5-flash-lite`
> (override with `EVAL_CONV_MODEL`), and the **feedback model** defaults to `gemini-3.5-flash-lite`
> (override with `EVAL_MODEL`).

### Learning-partner MVP integration

This repo embeds the `learning_partner` MVP as the `core.learning_partner`
package (in-repo, no install step) as a background learner model. The parent app
drives it:

- **On task pick** (`/start`, ADK `start_assessment`): the task (or custom
  interview question) is decomposed into a fine-grained knowledge graph
  (nodes + edges + a primary target) via an LLM call in `core/task_decomposer.py`.
  If no `GOOGLE_API_KEY` is set or the LLM call fails, a deterministic
  fallback creates a skill + problem node, so session startup never breaks.
- **On answer submit** (`/submit`, ADK `submit_answer`): the judge's result is
  converted into immutable MVP evidence and runs
  `evidence → learner-state update → misconception → frontier → next action`
  via `core/learner_bridge.py`. The parent's Bayesian `SkillState` scoring is
  untouched; the MVP model runs in parallel with full evidence traceability.
- **On report** (`/report`): a `learner` block (per-node states, frontier,
  misconceptions, next action) is attached to the response.

Storage: the MVP and the parent share one SQLite DB (`data/coach.db`). The
parent's raw-`sqlite3` tables (`assessments`, `learner_bindings`, auth) coexist
with the MVP's 13 SQLAlchemy tables in the same file; `learner_bindings` maps
`candidate → learner_id` so repeat sessions reuse a single learner model per
person. Override the MVP file with `LEARNING_PARTNER_DB_URL` if needed. The DB is
gitignored.

The MVP is LLM-free by design — all LLM decomposition happens in the parent app;
the MVP only stores what it is given.

#### Inspecting a learner from the CLI

The integration is backend-only (no UI surface by design). To see the MVP model
working, use the CLI inspector:

```bash
# Run one canned candidate through the full loop and print the snapshot
# (uses the deterministic fallback decomposer — no API key needed):
python -m core.learner_bridge --demo

# Print the snapshot for a real candidate (after they've answered tasks):
python -m core.learner_bridge alice@example.com

# Point at a different MVP DB if you overrode LEARNING_PARTNER_DB_URL:
python -m core.learner_bridge --db sqlite:///data/coach.db --demo
```

Output shows per-node `mastery`/`uncertainty`/`status`/`evidence`, the top
frontier entries, active misconceptions, and the policy's next action.

#### Why is `learning_partner` a package?

It started as a separate package (own `pyproject.toml`, own import root
`learning_partner.*`, own DB and migrations) that was installed with
`pip install -e ./learning_partner`. It has since been folded into the parent
repo as `core.learning_partner` (a sub-package of `core`, importable from the
repo root — no editable install, no extra dependency). Its internal modules use
relative imports; the parent reaches it via `from core.learning_partner...`.
Its legacy standalone CLI (`python -m core.learning_partner`) and Alembic
migrations remain under `core/learning_partner/`, but the runtime integration
uses `Base.metadata.create_all` on the shared `coach.db`.

## Running the agent

ADK provides both a command-line and a web interface for development.

### Web interface (recommended for testing)

Run `adk web` from **this project directory** (since `agent.py` is in `app/` subdirectory):

```bash
adk web --port 8000
```

Open `http://localhost:8000`, select **ai_research_coach** in the top-left, and start chatting. Example opening message:

> Evaluate candidate "Alice".

The agent will call `start_assessment`, walk through each task, collect answers, and finish with `get_report`.

### Custom UI (chat-style guest mode)

`./run.sh` serves a chat-style frontend (FastAPI + Vite) at `http://localhost:5173`.
Visitors land directly in **guest practice mode** — they can browse real questions,
request hints, and get unscored feedback on answers, with nothing saved. The header
shows **Log in** / **Sign up**, both of which sign in with **Google**. First-time
Google sign-in creates the account automatically; accounts unlock **scored
assessments**: answers are judged, feedback and a skills report are produced, and
history is saved to the account and resumable across devices. Anonymous practice is
enforced server-side (scored `mode=assessment` starts require an authenticated user).

After every submit — practice or assessed — the app pauses instead of jumping to the
next question. The judge's **coaching response** explains the misconception/gap and
walks the user step-by-step (with code examples) toward the correct solution; a
**Next question** button advances when the user is ready.

To enable Google login, create an OAuth 2.0 client in the
[Google Cloud Console](https://console.cloud.google.com/apis/credentials) (authorized
redirect URI `http://localhost:8001/api/auth/google/callback`) and add to `.env`:

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
# optional, defaults shown:
GOOGLE_REDIRECT_URI=http://localhost:8001/api/auth/google/callback
FRONTEND_URL=http://localhost:5173
```

Without those keys, guests can still use practice mode but Log in / Sign up are unavailable.

### Command-line interface

```bash
adk run app
```

> Run `adk run` from the project directory (agent is in `app/`).

> `adk web` is for development/debugging only — not for production deployment.

## How to extend (no code changes)

- **Add a question**: append an entry to `config/tasks.yaml` with a unique `id`, `skill`, and the code scoring fields (`function_name`/`scaffold`, `tests`, `tolerance`/`max_score`). Optionally add `hints` (ordered list of `{id, text, weight, reveal_threshold}`) and `expected_time_min`.
- **Add a skill**: add a block in `config/skills.yaml` (id, name, description, importance); it will automatically appear in reports.
- **Change the model**: set `EVAL_CONV_MODEL` (conversations) or `EVAL_MODEL` (feedback) in `.env` (e.g. `gemini-3.5-flash-lite`).

## Task type reference

All tasks use `code` evaluation — candidate code runs in a subprocess against hidden tests.

| Mode | Required fields | Scoring |
|------|-----------------|---------|
| **function** | `function_name`, `tests`, `tolerance` | per-test pass, partial credit |
| **scaffold** | `scaffold`, `tests` | hidden `assert` snippets, partial credit |

**Function mode** — the candidate implements a single function; `tests` entries use
`input` (list of args) and `expected`; comparison allows a float `tolerance`.

**Scaffold mode** — for class-based / multi-function tasks (e.g. a `MultiHeadAttention`
module or a `RequestBatcher`). The candidate edits a full scaffold; `tests` entries each
carry a hidden `code` snippet that runs against the module's namespace and must not raise.

## Persistence

Finished assessments are stored in a local SQLite database at `data/coach.db`
(created on first use; the `data/` dir is gitignored). After `get_report`, the agent can
summarize stored history via the `get_history` tool.

## Resilience & retry

Transient failures (rate limits `429`, server errors `5xx`, timeouts `408/504`) are handled
at the model API layer — both the agent's model (`Gemini(...)` with `retry_options`) and the
feedback client use exponential backoff retries (5 attempts, 1s → 30s, jitter) on retryable
HTTP codes. Tune via env vars: `EVAL_RETRY_ATTEMPTS`, `EVAL_RETRY_INITIAL_DELAY`,
`EVAL_RETRY_MAX_DELAY`.

- **Idempotent tools** — `submit_answer` returns the stored result for an already-scored task
  (no double-counting), and `start_assessment` resumes an in-progress session. If a turn fails
  after a tool ran, simply re-sending the last message continues safely.

## Scaling roadmap

- **Phase 0 (current)**: ADK agent + config task bank + local code runner + text report.
- **Phase 1**: replace the code evaluator's local subprocess with a real sandbox (e.g. container / e2b) and timed execution.
- **Phase 2**: make `picker` adaptive (drill into weak skills); add a web UI and richer rubrics.
- **Phase 3**: persistent storage + analytics across candidates; benchmarking; anti-cheat.

## References

- ADK Python quickstart: https://adk.dev/get-started/python/
- ADK agent samples (Python): https://github.com/google/adk-samples/tree/main/python/agents
