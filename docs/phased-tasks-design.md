# Phased tasks: one task, sequential phases (design)

Status: **implemented** (Phase 2). Version chains are retired from the active
selection path; ``coach.tasks.merge_version_chain`` migrates an existing chain
into one phased task.

Adds **phased delivery** to code-block tasks: a single task row whose `parts`
are problem-solving *phases* delivered one at a time, instead of a single
submission scored across all parts, or a chain of separate version rows.

- Each phase may cover **multiple functions** — a part is a phase of the
  problem-solving process, not a single function.
- A phase submission is scored on its own, with the candidate's previous code
  carried forward (`previous_code`), and a **teaching pause** before the next
  phase.
- A phase must pass to advance; failures loop back for retry, with a cap so a
  candidate can never get stuck.
- Starter code is **phase-scoped**: the editor shows only the current phase's
  scaffold until the candidate has code to carry forward.

Related: `docs/block-versioned-tasks-design.md` (blocks + version chains),
`AGENTS.md` (task/scoring overview).

## 1. Decisions

| Question | Decision |
|---|---|
| Delivery model | One task row; `parts` are phases delivered sequentially |
| Ability updates | **Per phase** (each submission is an observation: one global + that phase's tag/family) |
| Starter code | **Phase-scoped** — optional per-part `scaffold`, composed fallback |
| Failed phase | **Require pass to advance**; retry the same phase |
| Retry limit | **Cap then advance** (`PHASE_MAX_ATTEMPTS`, default 3) |
| Roadmap visibility | **Current phase only** (future phases hidden) |
| Pass threshold | Optional per-part `pass_score`, default `max(1, round(0.7 * max_score))` |
| Backward compatibility | Opt-in via `delivery='phased'`; `delivery='block'` (default) is unchanged |

## 2. Data model

**One new column** on `tasks`:

- `delivery TEXT DEFAULT 'block'` — `'block'` (default) or `'phased'`. Unknown
  values are rejected (422) on create/PATCH/seed. `tasks` stays in
  `_PRESERVED_TABLES`; `delivery` must not be added to `_DROPPED_TASK_COLUMNS`.

**Inside `parts_json` (no column change):** a part gains two optional fields,
preserved by `validate_parts`/`parse_parts`/`task_to_dict`:

- `scaffold` (≤16000) — the phase's starter code (used while no `previous_code`
  exists; the task-level `scaffold` is ignored for phased tasks).
- `pass_score` (int `0..max_score`, default `max(1, round(0.7 * max_score))`) —
  the score required to advance.

**No `session_steps` or `active_sessions` schema change:**

- Phase identity is derivable from existing JSON: `result_json.parts[].key` and
  `task_snapshot_json.parts[].pass_score`. Helpers `phase_state(task, session)`
  and `attempts_for_phase()` reconstruct it.
- Session progress (`task_progress: {task_id: phases_passed}`,
  `submission_index`) lives in the free-form `active_sessions.session_json`
  blob via `Session.to_dict`/`from_dict`.
- `step_index` must stop being `session.index` and become a monotonic
  `submission_index`, otherwise multiple phase attempts collide on the
  `uq_session_steps` unique index.

## 3. Backend changes

- `coach/db.py` — `create_schema()` adds the `delivery` migration
  (mirroring `language`).
- `coach/config.py` — `PHASE_PASS_FRACTION = 0.7`, `PHASE_MAX_ATTEMPTS = 3`.
- `coach/tasks.py` — `TaskModel.delivery`; `create_task`/`update_task` accept
  and validate `delivery`; `validate_parts`/`parse_parts` preserve part
  `scaffold`/`pass_score`; `task_to_dict` emits `delivery`.
- `coach/session.py` — `Session.task_progress`, `Session.submission_index`
  (persisted/restored); `phase_state(task, session)`; `task_view` is
  phase-aware for phased tasks: emits `delivery`, `phase_index` (1-based),
  `phase_total`, `parts: [active_part]`, `scaffold` = active part's scaffold,
  and `previous_code` = the last attempt for that phase/task.
- `coach/selection.py` — new branch after pending-generated and before the
  version successor: **continue/retry the active phased task** (next phase, or
  the same phase after a failure). Uses `last_submission` or the resume state.
- `backend/v1/sessions.py` —
  - `submit_answer`: resolve the current phase; score **only that part**
    (`targets = [parts[phase]]`) with `previous_code`; compute
    `passed = score >= pass_score`; update global ability + the part's
    tag/family; insert one step at `submission_index` (phase identity rides in
    `result_json`); if passed (or attempts hit the cap) advance
    `task_progress`, else return the same phase with `previous_code` = this
    attempt; when all phases are passed, add the task to `asked_task_ids`,
    append the aggregate result, and pick the next task.
  - Idempotency for phased tasks keys on `(task_id, phase, answer)`: an
    identical answer to the latest attempt returns the stored result; a new
    answer is a new attempt.
  - `get_session`: rebuild `task_progress` from steps (count passed phases per
    task) with the persisted value as fallback.
  - `_session_view`: task-ordinal `task_index`/`remaining` stay task-level;
    phase progress is carried in the task view.
- `coach/shares.py` — `feedback_from_steps` surfaces `phase_index`/part key so
  review renders phase bubbles; `_materialize_prefix` updates `task_progress`
  from inherited steps; `redo_step` targets a single phase.
- `coach/judge.py` — reword the system prompt from "one or more functions" to
  "parts/phases" so a multi-function phase is scored as a unit.
- `backend/v1/schemas.py` + `backend/v1/tasks.py` + `backend/admin_routes.py` —
  accept `delivery` on create/PATCH/admin seed.

## 4. Frontend changes

- `client.ts` — `Task.delivery`, `Task.phase_index`, `Task.phase_total`;
  `TaskPart.scaffold`; `TaskCreateBody.delivery`.
- `ChatView` — "Phase k of n" header; render only the active part's prompt
  (Markdown); button reads **Retry phase** on a failed phase and **Next phase**
  on a pass; the editor-init effect adds `phase_index` (and the attempt) to its
  dependency list so `previous_code` reloads each phase.
- `TaskPromptBubble` / `TaskPreview` — phase header + active-phase prompt
  (Markdown) for phased tasks; unchanged for blocks.
- `TaskEditor` — `delivery` selector and a per-part `scaffold` field.

## 5. Tests & docs

New/updated tests:

- Phase advance with code carry-forward; pass gate (`pass_score`);
  retry-then-cap-advance after `PHASE_MAX_ATTEMPTS`.
- Per-phase idempotency; `asked_task_ids` only after the final phase passes.
- Resume mid-phases reconstructs `task_progress`.
- `delivery='block'` behavior is unchanged.
- Shares/redo of a single phase.

Docs: update `AGENTS.md` (delivery field, phased tasks) and this document.

## 6. Execution order

1. Schema/config + tasks.py (delivery, part scaffold/pass_score)
2. steps/session (progress, `submission_index`, phase state)
3. selection + sessions routes
4. shares/redo
5. judge wording
6. frontend
7. tests + docs
8. merged task data + cleanup (below)

Run `pytest`, then `cd frontend && npm run lint && npx tsc -b && npm test`.

## 7. Merging the existing KV-cache version chain

The four version rows created for the KV-cache block allocator become phases
of one `delivery='phased'` task:

| Phase part key | Covers |
|---|---|
| `phase_1_basic_allocator` | `allocate`, `append_tokens`, `free` (fixed-size, boundary-only growth, all-or-nothing) |
| `phase_2_paged_mapping` | logical→physical block tables, shared prefixes |
| `phase_3_copy_on_write` | COW on shared blocks, `fork_sequence` |
| `phase_4_thread_safety` | synchronize all APIs for concurrent workers |

Steps:

1. Create one task with `delivery: "phased"`, `language: "cpp"`, primary tag
   `kv_cache`, explicit `difficulty`/`max_score`, and per-phase `prompt`,
   `scaffold`, `tags`, `max_score`, `difficulty`, `pass_score`.
2. Delete the four version rows (`task_0e61a9a5ed`, `task_2e22f61c75`,
   `task_2282264e5f`, `task_8794adee62`); their steps cascade.
3. Verify with a session scoped to the merged task: phase 1 fails → the same
   phase returns; phase 1 passes → phase 2 with `previous_code`; all phases
   passed → the task leaves the active slot.

## 8. Risks / notes

- **`step_index` uniqueness**: it must be a monotonic submission counter, not
  the task ordinal, or phase attempts collide on `uq_session_steps`.
- **Display counters**: session `task_index`/`remaining` are task-ordinal; phase
  progress is shown separately in the task view.
- **Cap-advance**: after the attempt cap a phase advances with `passed=false`
  recorded, so the aggregate reflects the miss.
- **Version chains vs phases**: `delivery='phased'` governs within-task
  sequencing; version successors still apply after a phased task completes.
