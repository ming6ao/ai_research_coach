# Explain This — selection-driven explanations

Status: **Current** (implemented)
Scope: learner session screen (`SessionLayout` + `ChatView`), right-hand explanation panel
Modules: `coach/explainer.py`, `coach/explanations.py`, `backend/v1/explanations.py`,
`frontend/src/components/Explain/`, `frontend/src/hooks/useTextSelection.ts`,
`frontend/src/stores/explainStore.ts`

> Implementation notes vs. the original proposal: one-shot responses (no
> streaming) and markdown/equation selections only (no Monaco selection) — both
> remain phase-2 items (§12). Failures are not persisted as rows; the route
> returns 502 and the client keeps a local retryable card. The new table is
> documented in `docs/data-model.md` (`explanations`, eight tables total).

## 1. Summary

A learner selects a block of text or a rendered equation anywhere in the
coaching conversation. A small floating bubble appears next to the selection
with the action **“Explain this”**. Clicking it sends the selected snippet —
plus the surrounding context (the active task/step, the paragraph it came
from) — to an LLM, and renders the explanation in a dedicated **right-hand
panel**. The screen becomes a two-pane layout: conversation + editor on the
left, explanations on the right. The panel keeps every explanation for the
session (and supports follow-up questions on each one).

The feature is a comprehension aid: it explains *concepts, notation, and
derivations*, and is explicitly forbidden from solving the learner's task.

### Goals
- Select rendered markdown text and KaTeX equations and get a grounded
  explanation without leaving the session.
- Keep the answer/editor flow intact; the panel is additive and collapsible.
- Persist explanations so a session can be reviewed later and so repeated
  selections are cheap (cache) and analyzable (signal of confusion).

### Non-goals
- It is **not** a hint system and never returns the task's solution.
- It does not touch mastery/beliefs (a self-initiated explanation request is
  not evidence of ability).
- Token streaming (phase 2), voice, and cross-session “explain” search are out
  of scope for v1.

## 2. User experience

1. Learner drags across a phrase in the question prompt, a coaching step, or a
   rendered formula.
2. On mouse-up, a **selection popover** appears anchored above the selection:
   `[ Explain this ]`. It disappears on Escape, scroll, or a click elsewhere.
3. Clicking it:
   - opens the right panel if closed;
   - immediately appends a **pending card** to the panel (quote + skeleton);
   - POSTs the request; when the response arrives the card fills with the
     explanation.
4. Each card shows the quoted snippet, a short title, the markdown/KaTeX answer,
   and related terms as chips. An optional input lets the learner ask a
   **follow-up** (“why is the variance divided by n−1?”) that appends to the
   same card as a thread.
5. The panel is independently scrollable; the left column continues to work
   (typing, submitting) while it is open.
6. On reload/resume, the panel restores the session's prior explanations.

Selection is limited to regions explicitly marked selectable (rendered
markdown), so it never fights with Monaco, the composer, or buttons.

## 3. Layout

`App.tsx` currently renders `<ChatView />` full-width when a session is active.
Introduce a `SessionLayout` that composes the existing chat column with the new
panel:

```tsx
// frontend/src/components/Session/SessionLayout.tsx
export function SessionLayout() {
  const { open } = useExplainStore();
  return (
    <div className="flex min-h-0 flex-1">
      <div className="relative min-w-0 flex-1">
        <ChatView />
      </div>
      {open && <ExplainPanel />}
    </div>
  );
}
```

- **Desktop (≥1024px):** left column flexes; right panel is a fixed
  `w-[380px] xl:w-[440px]` column with a left border and its own
  `overflow-y-auto`. The left column keeps `ChatView`'s existing centered,
  max-width scroll container.
- **Narrow (<1024px):** the panel becomes a right-side overlay drawer
  (`fixed inset-y-0 right-0 w-[88vw] max-w-sm`, with a dismiss backdrop) because
  a two-column split is unusable on a phone. The popover action opens it.
- **Open state** is stored in `localStorage` (`ai_coach_explain_open`); the
  panel starts closed and auto-opens on the first “Explain this”.
- A small toggle in the session header (right edge) lets the learner reopen or
  dismiss it manually.

The chat column's bubbles are wrapped in a selectable region:

```tsx
<div data-selectable data-source-kind="question" data-task-id={task.id}>
  <QuestionBubble ... />
</div>
```

`data-source-kind` ∈ `question | coaching | context`; `data-task-id` +
`phase_index` are read by the selection hook to build the request context.

## 4. Frontend architecture

### 4.1 Selection detection — `frontend/src/hooks/useTextSelection.ts`

A single hook mounted by `SessionLayout` listens on `document`
(`mouseup`/`keyup` to show, `selectionchange` to hide when collapsed):

1. Read `window.getSelection()`; bail if collapsed or the range is not inside a
   `[data-selectable]` ancestor.
2. Serialize the range to text with **math-aware cleanup** (see 4.2).
3. Compute an anchor rect from `range.getBoundingClientRect()` plus scroll
   offsets; clamp to the viewport.
4. Expose `{selection: {text, context, sourceKind, taskId, stepKey, rect} | null, clear()}`.
5. Cap at `MAX_SELECTION = 4000` characters (longer ⇒ hide the popover and show
   a “Select a shorter passage” tooltip). Derive `context` as the enclosing
   block's text, capped at 800 chars.

`SelectionPopover` renders through `createPortal(..., document.body)` so it is
never clipped by the scroll container. It hides on `mousedown` outside, Escape,
scroll, or resize.

### 4.2 Equations (KaTeX) and duplicated text

`lib/markdown.tsx` renders `$...$` / `$$...$$` via `katex.renderToString`.
KaTeX emits both a hidden MathML copy **and** an `aria-hidden="true"` visual
copy, so `selection.toString()` duplicates and garbles equations. Two changes:

1. Wrap `InlineMath` in a span that carries the source:
   ```tsx
   return <span data-latex={latex} dangerouslySetInnerHTML={{ __html: html }} />;
   ```
2. `serializeRange(range)` walks `range.cloneContents()` with a `TreeWalker`:
   - a `.katex` / `[data-latex]` element contributes `$<latex>$` (display mode
     uses `$$`), never its inner text;
   - nodes under `[aria-hidden="true"]` are skipped;
   - otherwise accumulate text nodes.
   Whitespace is collapsed and trimmed.

This keeps formulas selectable and sends the LLM clean LaTeX instead of
mangled glyphs. The serializer is a pure function over the cloned fragment and
is unit-tested on the string level (the repo has no DOM test dependency).

### 4.3 State — `frontend/src/stores/explainStore.ts`

A dedicated Zustand store (keeps `assessmentStore` focused on tasks/results):

```ts
export interface Explanation {
  id: string;                 // client id until the server responds
  selectedText: string;
  context: string;
  sourceKind: 'question' | 'coaching' | 'context' | 'code' | 'other';
  taskId?: string;
  stepKey?: string;
  question?: string;          // follow-up question, if any
  parentId?: string;          // thread root
  title?: string;
  answer?: string;            // markdown + $math$ + fenced code
  relatedTerms?: string[];
  status: 'pending' | 'ok' | 'error';
  error?: string;
  createdAt?: string;
}

interface ExplainState {
  open: boolean;
  items: Explanation[];
  ask: (req: AskRequest) => Promise<void>;
  askFollowUp: (parentId: string, question: string) => Promise<void>;
  retry: (id: string) => Promise<void>;
  loadForSession: (sessionId: string) => Promise<void>;
  openPanel(): void;
  closePanel(): void;
  clearSession(): void;
}
```

`ask()` appends a pending item, POSTs, then patches the item in place. `retry`
re-sends the stored request. `loadForSession` hydrates from the server on
resume/review. Failed calls leave the item with a retry action; they never
block the chat.

### 4.4 Components

| File | Responsibility |
|---|---|
| `components/Session/SessionLayout.tsx` | Two-pane wrapper + `<SelectionPopover/>` + panel toggle |
| `components/Explain/SelectionPopover.tsx` | Portal button “Explain this”, anchored to the selection |
| `components/Explain/ExplainPanel.tsx` | Right pane: header, empty state, scrollable thread list, auto-scroll |
| `components/Explain/ExplanationCard.tsx` | Quoted snippet, `Markdown` answer (`size="sm"`), term chips, follow-up input |
| `hooks/useTextSelection.ts` | Selection detection, range serialization, math cleanup |
| `stores/explainStore.ts` | Panel state + API orchestration |

`ExplanationCard` reuses `Markdown` (already supports KaTeX + `CodeBlock`) so
answers render consistently with coaching content.

### 4.5 API client additions — `frontend/src/api/client.ts`

```ts
export interface ExplainBody {
  task_id: string;
  step_key?: string;
  selected_text: string;   // 1..4000
  context?: string;        // <=800
  source_kind: 'question' | 'coaching' | 'context' | 'code' | 'other';
  question?: string;       // follow-up
  parent_id?: string;      // thread root, for follow-ups
}

explain: (sessionId: string, body: ExplainBody) =>
  v1<Explanation>('/sessions/' + encodeURIComponent(sessionId) + '/explanations', body),

listExplanations: (sessionId: string) =>
  v1<Explanation[]>('/sessions/' + encodeURIComponent(sessionId) + '/explanations', undefined, 'GET'),
```

## 5. Backend architecture

### 5.1 LLM helper — `coach/explainer.py`

Mirrors `coach/judge.py` / `coach/task_decomposer.py`: lazily created
`genai.Client` with `http_retry_options()`, JSON structured output, and a
raise-on-failure contract so the route can surface a retryable error.

```python
class Explainer:
    def explain(
        self,
        selection: str,
        *,
        context: str = "",
        step_prompt: str = "",
        task_notes: str = "",
        language: str = "python",
        question: str = "",
        prior_explanation: str = "",
    ) -> dict:
        """Return {"title": str, "explanation": str, "related_terms": [str]}.

        Raises RuntimeError when GOOGLE_API_KEY is missing or the call fails.
        """
```

The system prompt (adapted per call with the task context) enforces:

```
You are an expert AI/ML tutor. A learner highlighted a passage while working
on a coding task and asked for an explanation.

Return JSON with exactly three keys:
  "title": a short 3-8 word title naming the concept;
  "explanation": markdown that (1) defines the concept and each symbol,
    (2) derives/justifies any formula step by step, (3) gives one tiny concrete
    example, and (4) states why it matters for the task family;
  "related_terms": 2-5 short related concept names.

Rules:
  - Do NOT solve the learner's task, give the final answer, or write code that
    completes their step. Explain the underlying idea only.
  - Use $...$ for inline math and $$...$$ for display math.
  - Use fenced code blocks only for small illustrative snippets.
  - If the selection is ambiguous, explain the most likely technical meaning
    and say what you assumed.
```

User payload: the selection, the enclosing paragraph (`context`), the active
step prompt, the task's `context_notes`/`task_type`/`language`, the optional
follow-up question, and the parent explanation for follow-ups. All inputs are
length-capped before being sent.

### 5.2 Endpoints

Add to `backend/v1/sessions.py` (same auth/ownership path as answers):

```
POST /api/v1/sessions/{session_id}/explanations
  body: ExplainCreateRequest
  201  {"data": {id, selected_text, context, source_kind, task_id, step_key,
                 question, parent_id, title, explanation, related_terms,
                 model, cached, created_at}}
GET  /api/v1/sessions/{session_id}/explanations
  200  {"data": [Explanation, ...], "meta": {"total": n}}
```

Flow for `POST`:

1. `_load_session(store, session_id)` + `_check_owner(session, user)`.
2. Validate the task belongs to the session; resolve the active step prompt.
3. `request_hash = sha256(selected_text + context + question + task_id + step_key)`.
   If an `ok` row with the same hash exists for the session, return it with
   `cached: true` (no LLM call).
4. Call `Explainer().explain(...)`; on `RuntimeError` return **502** with a
   friendly `detail` (UI offers retry) and persist nothing but a transient
   error (or an `error` row — see below).
5. Persist an `explanations` row and return it.

New request models in `backend/v1/schemas.py`:

```python
class ExplainCreateRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    step_key: Optional[str] = Field(default=None, max_length=64)
    selected_text: str = Field(min_length=1, max_length=4000)
    context: Optional[str] = Field(default=None, max_length=800)
    source_kind: str = Field(default="other", max_length=16)
    question: Optional[str] = Field(default=None, max_length=1000)
    parent_id: Optional[str] = Field(default=None, max_length=36)
```

Routes can live in `backend/v1/sessions.py` or a new
`backend/v1/explanations.py` router registered in `backend/v1/__init__.py`;
the latter keeps the session module from growing.

### 5.3 Persistence — `coach/explanations.py`

A new SQLAlchemy model registered by `create_schema()` via
`Base.metadata.create_all` (no column migration required for existing DBs).

```python
class ExplanationModel(Base):
    __tablename__ = "explanations"
    __table_args__ = (
        Index("ix_explanations_session", "session_id"),
        Index("ix_explanations_candidate", "candidate"),
        Index("ix_explanations_task", "task_id"),
        Index("ix_explanations_hash", "session_id", "request_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)      # uuid
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate: Mapped[str] = mapped_column(String(255), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    step_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phase_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    context_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    related_terms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok|error
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

Helpers: `insert_explanation(...)`, `find_cached(session_id, request_hash)`,
`list_explanations(session_id)`, `delete_session_explanations(session_id)`.
`SessionState.delete` / `DELETE /sessions/{id}` must also delete the session's
explanations (add it next to `delete_session_data`).

**Why a separate table rather than `session_steps`?** Explanations are not
scored transitions and do not belong in the RL trajectory (`session_steps` is
the action/reward log). A selection can happen before, between, or after
submissions, and may never lead to a submission. An append-only event table
keeps `session_steps` semantically pure and makes the panel's history a plain
`SELECT ... ORDER BY created_at`.

**Why persist at all?** (a) resume/review renders the panel; (b) caching makes
repeat selections free; (c) it is a direct signal of where learners get stuck,
useful for curation and remediation.

## 6. Using the signal (without corrupting the learner model)

Explanations are **not** mastery evidence: a learner asking for an explanation
may be highly able but unfamiliar with notation. They must not update
`user_skill_beliefs`. Good uses:

- **Session review:** the panel replays in `openSession`, so a learner can
  revisit what they asked.
- **Curation:** aggregate the most-explained tasks/steps to find
  under-explained prompts (`GET` aggregation later).
- **Judge/remediation context (optional phase 2):** pass the selected terms of
  the current step into `LLMJudge.evaluate(...)` so coaching can pre-empt the
  confusion, and bias `coach/remediation.py` toward that skill when a step
  keeps generating explanation requests.

## 7. Caching, limits, and failure behavior

- **Dedup/cache:** identical `(selection, context, question, task, step)` in a
  session returns the stored answer (`cached: true`) with no LLM call.
- **Size caps:** selection 4000 chars, context 800, question 1000; enforced in
  the Pydantic model and by the UI.
- **Concurrency:** the client disables the popover action while a request for
  the same selection is pending.
- **Failure:** `RuntimeError` → HTTP 502 with a friendly detail; the card shows
  “Couldn't explain that — retry”. Offline → same error path (the PWA banner
  already warns sessions need a connection).
- **No API key:** `Explainer` raises immediately; the route returns 502 and
  logs once, matching `generate_followup_task`'s contract (tests stay hermetic
  by monkeypatching `Explainer`).

## 8. Accessibility and responsive behavior

- The popover is a real `<button>`; it is focusable and Escape-dismissable.
  Because selection is pointer-driven, also expose a keyboard path later:
  focus a bubble, press a shortcut to explain the focused block (phase 2).
- `aria-live="polite"` on the panel status so “Explanation ready” is announced.
- Panel heading is `role="complementary"` with a labelled close button.
- On narrow screens it is a modal drawer with `inert`/backdrop handling so
  focus does not leak to the chat behind it.

## 9. Review / resume integration

- `resumeSession` (store) or `SessionLayout`'s mount calls
  `explainStore.loadForSession(id)` for the opened session.
- The panel renders server rows in `created_at` order, grouped into threads by
  `parent_id`.
- `DELETE /api/v1/sessions/{id}` removes the session's explanations with the
  rest of the session data.

## 10. Testing

Backend (`tests/test_explain.py`):
- 201 + persistence for a valid request (monkeypatch `coach.explainer.Explainer`
  with a canned response).
- Dedup: a second identical request does not call the LLM and returns
  `cached: true`.
- 422 on empty/oversize `selected_text`; 404 when `task_id` is not in the
  session; 403 for another candidate's session; 502 when the explainer raises.
- Session delete removes its explanation rows.

Frontend (`frontend/tests/explain.test.ts`): pure helpers only (Node test
runner, no DOM dependency) — `normalizeSelectionText` whitespace collapsing,
KaTeX duplicate stripping, `requestKey` hashing, and the `explainStore`
pending→ok/error transitions against a mocked `apiClient`. DOM glue
(`serializeRange`, popover positioning) remains manually verified, consistent
with the repo's zero-dependency test setup.

## 11. Rollout plan

1. `coach/explanations.py` — model + CRUD; register in `create_schema`; cascade
   on session delete.
2. `coach/explainer.py` — prompt/schema/`Explainer.explain`.
3. `backend/v1/schemas.py` request models + `backend/v1/explanations.py` router
   (or routes in `sessions.py`); register in `backend/v1/__init__.py`.
4. `frontend/src/api/client.ts` types + methods; `explainStore`.
5. `useTextSelection` + `SelectionPopover`; mark `data-selectable` regions in
   `ChatView`; `InlineMath` `data-latex` change in `lib/markdown.tsx`.
6. `SessionLayout` + `ExplainPanel` + `ExplanationCard`; swap `ChatView` for
   `SessionLayout` in `App.tsx`.
7. Resume hydration + session-delete cascade.
8. Tests + update `docs/data-model.md` (table becomes eight tables).

### File map

| Area | Files |
|---|---|
| Data | `coach/explanations.py`, `coach/db.py` (register/cascade), `docs/data-model.md` |
| LLM | `coach/explainer.py` |
| API | `backend/v1/explanations.py` (new) or `backend/v1/sessions.py`, `backend/v1/schemas.py`, `backend/v1/__init__.py` |
| Client | `frontend/src/api/client.ts`, `frontend/src/stores/explainStore.ts` |
| UI | `frontend/src/hooks/useTextSelection.ts`, `frontend/src/components/Explain/*`, `frontend/src/components/Session/SessionLayout.tsx`, `frontend/src/components/Chat/ChatView.tsx`, `frontend/src/lib/markdown.tsx`, `frontend/src/App.tsx` |

## 12. Open questions

1. **Streaming** the explanation token-by-token (SSE) in v1, or one-shot?
   Recommendation: one-shot first; streaming is a clean phase-2 addition.
2. **Selection in the Monaco editor** — should selecting code in the editor
   also offer “Explain this” (via `editor.onDidChangeCursorSelection`)?
   Recommendation: phase 2; v1 covers question/coaching/context markdown.
3. **Anonymity of explanations** — persist for guests too (default yes, keyed by
   candidate) or signed-in only? Recommendation: persist for both, like mastery.
4. **Term-level reuse** — should highlighted terms be deduplicated across
   tasks into a glossary? Out of scope; the `explanations` rows are enough.
5. **Cost controls** — per-session request cap? Recommendation: cache first,
   then add a soft per-minute cap only if usage warrants it.
