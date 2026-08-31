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
