# Quick Task Authoring — draft a task from step prompts

Status: **Implemented** (all phases)
Scope: curator UI (`frontend/src/components/Curator/`), task API (`backend/v1/tasks.py`),
LLM helpers (`coach/task_decomposer.py`, `coach/scaffold_backfill.py`)
Modules touched: `coach/task_decomposer.py`, `backend/v1/schemas.py`,
`backend/v1/tasks.py`, `frontend/src/api/client.ts`,
`frontend/src/components/Curator/TaskEditor.tsx`

## 1. Summary

Authoring a task in the curator UI is currently tedious: the editor exposes a
language dropdown, a task-type dropdown, and per-step fields for key, prompt,
`max_score`, `difficulty`, `pass_score`, a primary skill, up to two secondary
skills, and starter code — for every step. The curator must populate all of
them before a question can be created.

This proposal adds a **Quick create** path: the curator pastes the step
prompts, one per block, and a single LLM call fills in the mechanical
metadata — internal step keys, `max_score`, `difficulty`, `pass_score`,
taxonomy tags, starter code, task type, and `context_notes`. The result is
returned as a **draft task body** that hydrates the existing editor; the
curator reviews and edits it, then clicks the existing **Create question**.

The LLM proposes; the human commits. No generated task is ever persisted
without the curator pressing Create. The curator can also **iterate**: after a
draft is generated they can send a plain-English instruction ("make step 2
harder", "rename the entry point", "split the scaffold into two functions")
and the LLM revises the draft for review.

## 2. Recommendation: project code, not an agent skill

This belongs in the application, not in an agent skill:

- **Users are curators, not the agent.** The feature must be discoverable in
  the web UI by any signed-in curator. An agent skill only helps during a
  developer/tooling session and cannot be reached from the product.
- **Auth, ownership, and persistence live in the app.** A skill would have to
  re-implement task-ownership rules and DB writes that already exist.
- **The LLM plumbing already exists** (see §3). There is nothing agent-specific
  to gain.
- **Testability.** A backend endpoint is covered by the existing pytest suite
  and the frontend by `node:test`; a skill is neither.

There is no agent-skill or bulk-import variant planned; the feature is
self-contained in the app.

## 3. What already exists (reuse map)

| Need | Existing asset |
|------|----------------|
| Auto-tags (primary/secondary leaf skills) + `context_notes` | `TaskDecomposer.describe_and_categorize` (`coach/task_decomposer.py`) |
| Per-step starter code | `TaskDecomposer.generate_scaffold` + `_SCAFFOLD_SYSTEM_PROMPT` |
| Stub hygiene + syntax validation | `validate_scaffold` / `_validate_python_stub` (`coach/scaffold_backfill.py`) |
| Retry-with-feedback for rejected LLM output | `plan_generate` (`coach/scaffold_backfill.py`) |
| Parts / tag / score / scaffold validation | `coach.tasks.validate_parts` (scaffold required), `coach.taxonomy.validate`, `default_pass_score` |
| Request-level LLM cache pattern | `_COMBINED_CACHE` (`backend/v1/sessions.py`) |

The only genuinely new capability is: **curator-supplied step prompts →
a fully-populated task body for review.**

## 4. Design

### 4.1 Curator UX

When creating a *new* question, `TaskEditor` shows a **Quick create** panel
above the existing form:

- A textarea: one step prompt per block, separated by a blank line or a
  `---` line.
- Optional language, task type, and difficulty hint selects.
- Button **Fill in details** → `POST /api/v1/tasks/draft` → hydrate the
  existing `parts` / `language` / `task_type` form state.
- On success the draft hydrates the form; the curator reviews/edits by hand
  and/or **refines with the LLM** (see §4.3), then clicks the existing
  **Create question** (which calls the existing `POST /api/v1/tasks`).
- A **Quick / Detailed** toggle lets power users skip the assistant entirely.

Step input is **curator-delimited** (predictable step count). Starting from a
single unbroken blob and asking the LLM to split it is a possible later
enhancement, not the default.

### 4.2 Backend endpoint

`POST /api/v1/tasks/draft` — authenticated, additive, no DB migration. One
endpoint serves two modes:

- **Initial draft** — send `steps` (the curator's per-step prompts).
- **Refinement** — send the current `draft` plus a plain-English `instruction`
  and omit `steps`; the returned draft replaces the one under review.

```jsonc
// initial draft
{
  "steps": [
    "Implement scaled_dot_product_attention(Q, K, V).",
    "Now add causal masking so position i cannot attend to j > i."
  ],
  "language": "python",      // optional, default "python"
  "task_type": "implement",  // optional hint
  "difficulty": 2,           // optional hint applied to every step
  "context": "audience: beginner transformers"  // optional steering
}

// refinement of an existing draft
{
  "draft": { "parts": [ /* ...current form state... */ ], "language": "python" },
  "instruction": "Make step 2 harder and rewrite its scaffold."
}

// response — exactly the shape the form already submits
{
  "data": {
    "parts": [
      { "key": "...", "prompt": "...", "tags": {"primary": "...", "secondary": []},
        "max_score": 5, "difficulty": 2, "pass_score": 4, "scaffold": "..." }
    ],
    "language": "python",
    "task_type": "implement",
    "context_notes": "...",
    "tags": { "primary": "...", "secondary": ["..."] }
  }
}
```

The route returns a draft only; it does **not** write to `tasks`. Register it
before the parameterized `GET /tasks/{task_id}` for clarity, though the methods
differ so there is no actual conflict.

Limits: 1–5 steps per task, bounded total input length; signed-in curators
only. A 6-step request is rejected.

### 4.3 Iterating on the draft (LLM refinement)

The curator is never stuck with the first draft. From the Quick create panel
they type an instruction, and the current draft is sent back through the same
endpoint (§4.2); the LLM applies the change and returns a revised draft that
replaces the form state. Typical instructions:

- "Make step 2 easier and simplify its scaffold."
- "Use the same primary skill for every step."
- "Rewrite step 1 to name the exact function signature."

Refinement is validated exactly like an initial draft (taxonomy tags, scaffold
hygiene, step count) and never bypasses the editor: the curator still presses
Create. Hand edits to the form are also preserved as the starting point for
the next refinement.

### 4.4 `TaskDecomposer.draft_task(...)`

One structured call (new `_DRAFT_SYSTEM_PROMPT` + `_DRAFT_SCHEMA`) that returns,
per step: `key`, a cleaned/expanded `prompt` (intent preserved, no answer
revealed), `difficulty`, `max_score`, optional `pass_score`, `primary_tag`,
`secondary_tag[]`, `scaffold`; plus task-level `task_type` and `context_notes`.

After the call:

1. Normalize and validate with `coach.tasks.validate_parts` and
   `coach.taxonomy.validate`.
2. Validate each scaffold with the existing hygiene/AST checker; on problems,
   retry with feedback (the same loop as `scaffold_backfill.plan_generate`).
3. Reject a step-count mismatch between request and response.
4. **No scaffold is ever synthesized.** A step whose scaffold the model omitted
   or produced invalid keeps an empty scaffold, and the editor then blocks
   creation (see §4.5).
5. **Offline / deterministic fallback** when `GOOGLE_API_KEY` is absent or the
   call fails: keys from prompt slugs, `difficulty` from the hint (default 2),
   `max_score=5`, default `pass_score`, empty `scaffold`, and empty tags so the
   curator picks skills manually. A missing key degrades to an editable draft,
   not a 500 — but the missing starter code still has to be filled in by hand.

Reuse the request-cache pattern for repeated identical drafts. The refinement
path takes an existing draft plus the instruction and returns the same
validated shape.

### 4.5 Frontend

- `frontend/src/api/client.ts`: add `draftTask(body): Promise<TaskCreateBody>`
  (the same call backs both the initial draft and refinement by varying the
  body).
- `frontend/src/components/Curator/TaskEditor.tsx`: add the Quick create panel,
  the refinement input, and hydrate the existing `PartDraft[]` state (reuse the
  `partsToDrafts` shape). `buildBody` reuses `findStepDraftError`, which
  **blocks Create when a non-empty step has no starter code**, focuses that
  step, and shows the message ("Step N needs starter code.").
- Extract the split heuristic into a pure helper, e.g.
  `splitStepPrompts(text): string[]`, so it is unit-testable independently of
  React.

## 5. Guardrails

- Signed-in curators only; capability is scoped by the existing auth deps.
- All LLM output validated server-side before it reaches the client.
- The endpoint never persists; persistence stays `POST /api/v1/tasks`.
- Step count capped at 5 and input size bounded; one LLM call per draft or
  refinement.
- A step without an LLM-generated scaffold is never filled in automatically:
  the curator editor blocks **Create question** until starter code is added, and
  the server rejects a missing scaffold on `POST`/`PATCH` with 422
  (`coach.tasks.validate_parts`).
- Refinements are validated exactly like initial drafts (tags, scaffold
  hygiene, step count).
- Graceful degradation without an API key (editable fallback draft).
- No new dependencies, no DB schema change.

## 6. Implementation phases

1. **`coach/task_decomposer.py`** — add `_DRAFT_SYSTEM_PROMPT`,
   `_DRAFT_SCHEMA`, and `draft_task(...)` (initial draft and refinement
   paths). Factor `validate_scaffold` out of `coach/scaffold_backfill.py` into
   an importable helper rather than duplicating it.
2. **`backend/v1/schemas.py` + `backend/v1/tasks.py`** — `TaskDraftRequest`
   (initial-draft and refinement modes) and `POST /api/v1/tasks/draft`.
3. **`frontend/src/api/client.ts` + `TaskEditor.tsx`** — `draftTask`, the
   Quick create panel, the refinement input, and the Quick/Detailed toggle.
4. **Docs** — update `AGENTS.md` (endpoint list and Curator UI notes).

## 7. Testing

- **Backend (`tests/`)**: offline (no API key) draft returns a valid fallback
  shape with **no synthesized scaffold**; an LLM payload missing a scaffold
  stays empty and a leaking scaffold is not substituted; empty/oversized step
  lists → 422 (a 6-step task is rejected); step-count mismatch rejected; a
  refinement applies an instruction and revalidates.
- **Frontend (`frontend/`, `node:test`)**: `splitStepPrompts` covers blank
  line, `---`, and single-step cases; `findStepDraftError` rejects a step with
  no starter code (ignoring empty trailing steps) and reports its index; draft
  hydration maps LLM parts into `PartDraft[]` including optional
  `pass_score`/`scaffold`.

## 8. Open decisions

1. Always require curator review (recommended), or allow one-click
   "create from draft"?
2. Step input: curator-delimited only (recommended first), or also support
   "one blob → LLM splits into steps"?
3. Support enriching a single existing prompt through the same endpoint
   (proposed: yes — it is just a 1-step draft).
4. Refinement granularity: whole-task instructions only (proposed), or also
   per-step instructions targeted at a specific step?
