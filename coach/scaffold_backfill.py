"""Backfill per-step starter code (``scaffold``) for the task bank.

Every step of every task should open the editor with a sane,
non-answer-revealing stub. Two paths populate the ones that are empty:

``recover``
    Deterministic and offline. A few legacy tasks stored a single
    task-level ``scaffold`` holding one ``def`` per step, which phased
    delivery no longer reads (``coach.session._phase_scaffold`` looks only at
    ``part["scaffold"]``). Split that blob on top-level ``def`` boundaries
    and distribute one chunk per step, matching each chunk's ``def`` name to
    the step key so the split can never silently misalign. Helper defs that
    are not themselves steps (e.g. a shared ``sigmoid``) stay attached to the
    next step.

``generate``
    LLM-assisted. Propose an entry-point signature + stub for each remaining
    empty step, conditioned on the step prompt, language, tags and a sibling
    step's scaffold as a style exemplar. The signature is also appended to
    the step prompt so the judge and the editor agree on the API.

Both paths are idempotent (never overwrite a non-empty scaffold unless
``--force``), dry-run by default, and back up the DB before writing. The
generated path rejects and retries any stub with an implementation body,
leaked instance state, no TODO marker, or invalid syntax.

    python -m coach.scaffold_backfill audit
    python -m coach.scaffold_backfill recover   [--apply] [--force]
    python -m coach.scaffold_backfill generate  [--apply] [--task ID] [--force]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
from typing import Optional

from coach.db import DB_PATH

# Same heuristics as ``coach.migrate.hygiene_report``: starter code must not
# declare private members or instance state.
_HYGIENE_PRIVATE = re.compile(r"(^|\n)\s*(private|protected)\s*:")
_HYGIENE_MEMBER = re.compile(r"(^|\n)\s*(?:mutable\s+)?[\w:<>,\s*&]+\s+\w+_\s*(?:=|;)")
_HYGIENE_SELF = re.compile(r"(^|\n)\s*self\.\w+\s*=")
_TODO_MARK = re.compile(r"#|//|/\*")
_DEF_NAME = re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)
_TOP_DEF_LINE = re.compile(r"^(def|class)\s")

MAX_SCAFFOLD_CHARS = 16000


# ---------------------------------------------------------------------------
# loading / audit
# ---------------------------------------------------------------------------


def _load_tasks(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT id, owner, source, language, scaffold, parts_json, tags_json, "
        "context_notes, task_type FROM tasks ORDER BY created_at"
    ).fetchall()
    out = []
    for r in rows:
        try:
            parts = json.loads(r[5] or "[]")
        except Exception:
            parts = []
        if not isinstance(parts, list):
            parts = []
        out.append(
            {
                "id": r[0],
                "owner": r[1],
                "source": r[2],
                "language": r[3] or "python",
                "scaffold": r[4],
                "parts": parts,
                "tags": _safe_json(r[6], {}),
                "context_notes": r[7] or "",
                "task_type": r[8] or "implement",
            }
        )
    return out


def _safe_json(raw, default):
    try:
        value = json.loads(raw or "")
        return value if value is not None else default
    except Exception:
        return default


def audit() -> dict:
    """Read-only: list every step that has no starter code."""
    con = sqlite3.connect(DB_PATH)
    try:
        tasks = _load_tasks(con)
    finally:
        con.close()
    missing = []
    total_steps = 0
    for t in tasks:
        for p in t["parts"]:
            total_steps += 1
            if not (p.get("scaffold") or "").strip():
                missing.append(
                    {
                        "task_id": t["id"],
                        "source": t["source"],
                        "language": t["language"],
                        "step": p.get("key"),
                        "task_scaffold": bool((t.get("scaffold") or "").strip()),
                    }
                )
    return {
        "tasks": len(tasks),
        "steps": total_steps,
        "with_scaffold": total_steps - len(missing),
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# deterministic recovery
# ---------------------------------------------------------------------------


def split_scaffold(scaffold: str) -> tuple[list[str], list[str]]:
    """Split a task-level scaffold into per-``def`` chunks.

    Returns ``(chunks, leftover)``. Top-level imports/blank lines seen before
    a ``def`` become a preamble attached to that chunk; a trailing
    module-level statement after the last ``def`` lands in ``leftover`` so the
    caller can refuse to guess.
    """
    chunks: list[str] = []
    preamble: list[str] = []
    current: Optional[list[str]] = None
    for line in (scaffold or "").splitlines():
        is_top = bool(line.strip()) and line[:1] not in (" ", "\t")
        if is_top and _TOP_DEF_LINE.match(line):
            pre = list(preamble)
            while pre and not pre[-1].strip():
                pre.pop()
            current = (pre + ["", line]) if pre else [line]
            preamble = []
            chunks.append(current)
            continue
        if current is not None and not is_top:
            current.append(line)
        else:
            preamble.append(line)
    # Anything left in ``preamble`` sits after the last ``def``: refuse to guess.
    leftover = [ln for ln in preamble if ln.strip()]
    return ["\n".join(c).strip() for c in chunks], leftover


def plan_recover(tasks: list[dict], force: bool = False) -> tuple[dict, list[dict]]:
    """Map each legacy task-level scaffold onto its steps by ``def`` name."""
    plan: dict[str, list[dict]] = {}
    report: list[dict] = []
    for t in tasks:
        top = (t.get("scaffold") or "").strip()
        if not top:
            continue
        parts = t["parts"]
        chunks, leftover = split_scaffold(top)
        keys = [p.get("key") for p in parts]
        key_set = set(keys)
        if not key_set:
            report.append({"task_id": t["id"], "status": "skip", "reason": "no steps"})
            continue
        if leftover:
            report.append(
                {"task_id": t["id"], "status": "skip", "reason": "trailing module-level code"}
            )
            continue
        recovered: dict[str, str] = {}
        pending_helpers: list[str] = []
        for chunk in chunks:
            names = _DEF_NAME.findall(chunk)
            name = names[0] if names else None
            if name in key_set:
                recovered[name] = "\n\n".join(pending_helpers + [chunk])
                pending_helpers = []
            else:
                pending_helpers.append(chunk)
        if pending_helpers:
            report.append(
                {
                    "task_id": t["id"],
                    "status": "skip",
                    "reason": "trailing helper def not attached to a step",
                }
            )
            continue
        missing_keys = [k for k in keys if k not in recovered]
        if missing_keys:
            report.append(
                {
                    "task_id": t["id"],
                    "status": "skip",
                    "reason": f"no scaffold chunk for steps {missing_keys}",
                }
            )
            continue
        new_parts = []
        filled = 0
        for part in parts:
            key = part.get("key")
            if (part.get("scaffold") or "").strip() and not force:
                new_parts.append(part)
                continue
            new_parts.append({**part, "scaffold": recovered[key]})
            filled += 1
        if filled:
            plan[t["id"]] = new_parts
            report.append(
                {"task_id": t["id"], "status": "recover", "steps_filled": filled}
            )
        else:
            report.append({"task_id": t["id"], "status": "noop", "reason": "nothing empty"})
    return plan, report


# ---------------------------------------------------------------------------
# LLM generation + validation
# ---------------------------------------------------------------------------


def validate_scaffold(scaffold: str, *, language: str = "python") -> list[str]:
    """Return a list of reasons the stub is unusable / answer-revealing."""
    problems: list[str] = []
    text = (scaffold or "").strip()
    if not text:
        return ["empty"]
    if len(text) > MAX_SCAFFOLD_CHARS:
        problems.append("too long")
    if not _TODO_MARK.search(text):
        problems.append("no TODO marker")
    if (
        _HYGIENE_PRIVATE.search(text)
        or _HYGIENE_MEMBER.search(text)
        or _HYGIENE_SELF.search(text)
    ):
        problems.append("leaks internals")
    if language == "python":
        problems.extend(_validate_python_stub(text))
    else:
        if not re.search(r"[A-Za-z_]\w*\s+\w+\s*\(", text):
            problems.append("no function signature")
    return problems


def _validate_python_stub(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"invalid Python syntax: {exc.msg}"]
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not funcs:
        return ["no function definition"]
    problems: list[str] = []
    for node in tree.body:
        if isinstance(
            node,
            (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring
        problems.append("unexpected top-level statement")
        break
    for fn in funcs:
        if not _is_stub_body(fn.body):
            problems.append(f"{fn.name} has an implementation body")
    return problems


def _is_stub_body(body: list) -> bool:
    """True when a function body only comments/docstrings/pass/NotImplemented."""
    for node in body:
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Raise):
            exc = node.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                continue
        return False
    return True


def _first_def_name(text: str) -> Optional[str]:
    m = _DEF_NAME.search(text or "")
    return m.group(1) if m else None


def annotate_prompt(prompt: str, signature: str) -> str:
    """Append the entry-point signature unless the prompt already names it."""
    sig = (signature or "").strip().rstrip(":").strip()
    name = _first_def_name(sig)
    if not name:
        return prompt
    if re.search(rf"`\s*(?:def\s+)?{re.escape(name)}\s*\(", prompt or ""):
        return prompt
    return f"{(prompt or '').rstrip()}\n\nEntry point: `{sig}`"


def plan_generate(
    tasks: list[dict],
    *,
    task_ids: Optional[set[str]] = None,
    force: bool = False,
    annotate: bool = True,
    retries: int = 3,
    generator=None,
    log=print,
) -> tuple[dict, list[dict]]:
    """Generate stubs for empty steps (and annotate their prompts)."""
    from coach.task_decomposer import TaskDecomposer

    gen = generator or TaskDecomposer()
    plan: dict[str, list[dict]] = {}
    failures: list[dict] = []
    for t in tasks:
        if task_ids and t["id"] not in task_ids:
            continue
        parts = t["parts"]
        exemplar = next(
            (
                p.get("scaffold")
                for p in parts
                if (p.get("scaffold") or "").strip()
            ),
            "",
        )
        new_parts: list[dict] = []
        changed = 0
        for part in parts:
            key = part.get("key")
            if (part.get("scaffold") or "").strip() and not force:
                new_parts.append(part)
                continue
            feedback = ""
            chosen: Optional[dict] = None
            for _attempt in range(max(1, retries)):
                try:
                    cand = gen.generate_scaffold(
                        part.get("prompt", ""),
                        language=t["language"],
                        step_key=key,
                        context_notes=t.get("context_notes", ""),
                        exemplar=exemplar,
                        feedback=feedback,
                    )
                except Exception as exc:  # noqa: BLE001 - report, do not abort the run
                    feedback = f"generation error: {exc}"
                    log(f"  ! {t['id']}/{key}: {exc}")
                    continue
                problems = validate_scaffold(cand["scaffold"], language=t["language"])
                if not problems:
                    chosen = cand
                    break
                feedback = "; ".join(problems)
                log(f"  ! {t['id']}/{key}: rejected ({feedback})")
            if chosen is None:
                failures.append(
                    {"task_id": t["id"], "step": key, "reason": feedback or "generation failed"}
                )
                new_parts.append(part)
                continue
            new = {**part, "scaffold": chosen["scaffold"]}
            if annotate:
                # Annotate with the signature that actually appears in the
                # scaffold so the prompt and editor can never disagree.
                scaffold_def = _first_def_name(chosen["scaffold"]) or key
                sig = chosen.get("signature") or ""
                if _first_def_name(sig) != scaffold_def:
                    sig = f"def {scaffold_def}(...)"
                new["prompt"] = annotate_prompt(part.get("prompt", ""), sig)
            new_parts.append(new)
            changed += 1
        if changed:
            plan[t["id"]] = new_parts
    return plan, failures


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def apply_plan(con: sqlite3.Connection, plan: dict[str, list[dict]], *, clear_task_scaffold: bool) -> dict:
    """Write new ``parts_json`` (and refresh session snapshots)."""
    cur = con.cursor()
    cur.execute("BEGIN")
    tasks_changed = 0
    for tid, parts in plan.items():
        cur.execute(
            "UPDATE tasks SET parts_json=? WHERE id=?",
            (json.dumps(parts), tid),
        )
        if clear_task_scaffold:
            cur.execute("UPDATE tasks SET scaffold=NULL WHERE id=?", (tid,))
        tasks_changed += 1
    sessions_changed = 0
    rows = cur.execute("SELECT session_id, session_json FROM active_sessions").fetchall()
    for sid, sj in rows:
        data = _safe_json(sj, {})
        sess = data.get("session") or {}
        touched = False
        for task in sess.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            parts = plan.get(task.get("id"))
            if not parts:
                continue
            task["parts"] = parts
            if parts:
                task["prompt"] = parts[0].get("prompt", task.get("prompt", ""))
            if clear_task_scaffold:
                task.pop("scaffold", None)
            touched = True
        if touched:
            cur.execute(
                "UPDATE active_sessions SET session_json=? WHERE session_id=?",
                (json.dumps(data), sid),
            )
            sessions_changed += 1
    con.commit()
    return {"tasks": tasks_changed, "sessions": sessions_changed}


def _summarize(plan: dict[str, list[dict]]) -> dict:
    steps = sum(len(parts) for parts in plan.values())
    filled = sum(
        1
        for parts in plan.values()
        for p in parts
        if (p.get("scaffold") or "").strip()
    )
    return {"tasks": len(plan), "steps": steps, "steps_with_scaffold": filled}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load the repo ``.env`` so the generate path sees GOOGLE_API_KEY.

    The app loads it in ``backend.main``; admin CLIs run standalone, so the
    LLM path must load it here (audit/recover stay offline either way).
    """
    try:
        from pathlib import Path

        from dotenv import load_dotenv

        load_dotenv(Path(DB_PATH).resolve().parent.parent / ".env")
    except Exception:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(prog="coach.scaffold_backfill", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["audit", "recover", "generate"])
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--no-backup", action="store_true", help="with --apply, skip the DB backup")
    parser.add_argument("--force", action="store_true", help="overwrite non-empty scaffolds")
    parser.add_argument("--task", action="append", default=None, help="limit generate to a task id (repeatable)")
    parser.add_argument("--no-annotate", action="store_true", help="do not append the signature to prompts")
    parser.add_argument("--retries", type=int, default=3, help="LLM attempts per rejected stub")
    parser.add_argument("--show", action="store_true", help="print the resulting scaffolds (dry run)")
    parser.add_argument("--save", default=None, help="write the generated plan to a JSON file")
    parser.add_argument("--from", dest="from_plan", default=None, help="apply a saved plan instead of calling the LLM")
    args = parser.parse_args(argv)

    con = sqlite3.connect(DB_PATH)
    try:
        tasks = _load_tasks(con)

        if args.command == "audit":
            report = audit()
            print(json.dumps(report, indent=2))
            return 0

        if args.command == "recover":
            plan, report = plan_recover(tasks, force=args.force)
            print(json.dumps({"apply": args.apply, "plan": _summarize(plan), "report": report}, indent=2))
            if args.apply and plan:
                if not args.no_backup:
                    from coach.migrate import backup_database

                    dest = backup_database()
                    if dest:
                        print(f"backup written: {dest}")
                print(json.dumps(apply_plan(con, plan, clear_task_scaffold=True), indent=2))
            return 0

        # generate
        failures: list[dict] = []
        if args.from_plan:
            with open(args.from_plan, encoding="utf-8") as fh:
                loaded = json.load(fh)
            plan = {tid: parts for tid, parts in loaded.items() if isinstance(parts, list)}
        else:
            task_ids = set(args.task) if args.task else None
            plan, failures = plan_generate(
                tasks,
                task_ids=task_ids,
                force=args.force,
                annotate=not args.no_annotate,
                retries=args.retries,
            )
        if args.save:
            with open(args.save, "w", encoding="utf-8") as fh:
                json.dump(plan, fh, indent=2)
            print(f"plan written: {args.save}")
        result = {
            "apply": args.apply,
            "plan": _summarize(plan),
            "failures": failures,
        }
        if args.show:
            result["scaffolds"] = {
                tid: {p.get("key"): (p.get("scaffold") or "") for p in parts}
                for tid, parts in plan.items()
            }
        print(json.dumps(result, indent=2))
        if args.apply and plan:
            if not args.no_backup:
                from coach.migrate import backup_database

                dest = backup_database()
                if dest:
                    print(f"backup written: {dest}")
            print(json.dumps(apply_plan(con, plan, clear_task_scaffold=False), indent=2))
        return 1 if failures else 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
