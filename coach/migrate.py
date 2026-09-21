"""Admin CLI: migrate the retired taxonomy in place, and report bank coverage.

Run with the server stopped. The default is a read-only **dry run** that
reports exactly what would change; pass ``--apply`` to write (a DB backup is
taken first unless ``--no-backup``).

    python -m coach.migrate                      # dry-run: report dispositions
    python -m coach.migrate --apply              # backup + migrate in place
    python -m coach.migrate coverage             # per-skill bank coverage
    python -m coach.migrate hygiene              # read-only prompt/scaffold audit
    python -m coach.migrate delivery [--apply]   # normalize to step-by-step
    python -m coach.migrate sessions [--apply]   # drop sessions with no answer

In-place migration rewrites, in order: task tags (block + parts), per-node
belief rows, active-session snapshots, and session-step snapshots/states.
Task ids, owners, and attempt links are preserved.

The separate ``delivery`` command normalizes every task (and stored snapshot)
to step-by-step delivery: block tasks become phased and legacy partless
*snapshots* are wrapped into one part. (Live partless DB rows are wrapped by
``create_schema`` when it drops the retired ``prompt`` column.) It is dry-run
by default and backs up first with ``--apply``.

``--on-unmapped`` controls tasks whose primary/part primary refers to a retired
tag with no current counterpart:

- ``delete`` (default): remove the task (and cascade its steps).
- ``fallback``: retag to ``--fallback <leaf skill>`` so it can be re-classified
  later in the curator UI.
- ``keep``: leave the legacy tag untouched (will fail later PATCH validation).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from coach.taxonomy_migration import OLD_FAMILIES, map_secondary, map_state, map_tag


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_file() -> Path:
    import coach.db as db

    return Path(db.DB_PATH)


def backup_database() -> Optional[str]:
    """Copy the SQLite file (plus -wal/-shm) into ``data/backups/``."""
    src = _db_file()
    if not src.exists():
        return None
    dest_dir = src.parent / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"{src.stem}-{stamp}{src.suffix}"
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        extra = Path(str(src) + suffix)
        if extra.exists():
            try:
                shutil.copy2(extra, Path(str(dest) + suffix))
            except Exception:
                pass
    return str(dest)


# ---------------------------------------------------------------------------
# tag remapping helpers
# ---------------------------------------------------------------------------


def _retag(tags: Optional[dict], mode: str, fallback: Optional[str]) -> tuple[Optional[dict], Optional[str], int]:
    """Map one tags block.

    Returns ``(new_tags | None, unmapped_primary | None, removed_secondary)``.
    ``new_tags`` is ``None`` only when there is no usable primary (which only
    happens in ``delete`` mode for a task that will be dropped).
    """
    tags = tags or {}
    old_primary = tags.get("primary")
    old_secondary = list(tags.get("secondary") or [])

    leaf = map_tag(old_primary)
    unmapped: Optional[str] = None
    if old_primary and leaf is None:
        unmapped = old_primary
        if mode == "fallback":
            leaf = fallback
        elif mode == "keep":
            leaf = old_primary
    new_secondary = map_secondary(old_secondary)
    removed = len({s for s in old_secondary if map_tag(s) is None})

    if not leaf:
        return None, unmapped or old_primary or "(missing)", removed
    return {"primary": leaf, "secondary": new_secondary}, unmapped, removed


def _remap_task(task: dict, mode: str, fallback: Optional[str]) -> bool:
    """Remap a task dict's block + part tags in place.

    Returns ``False`` when the task must be dropped (delete mode, unmappable
    critical primary). Part tags are the scoring units, so any unmappable part
    primary makes the whole task a drop candidate.
    """
    tags = task.get("tags")
    if isinstance(tags, dict):
        new, _unmapped, _removed = _retag(tags, mode, fallback)
        if new is not None:
            task["tags"] = new
        elif mode == "delete":
            return False

    parts = task.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            pnew, _punmapped, _premoved = _retag(part.get("tags"), mode, fallback)
            if pnew is not None:
                part["tags"] = pnew
            elif mode == "delete":
                return False
    return True


# ---------------------------------------------------------------------------
# table migrations
# ---------------------------------------------------------------------------


def migrate_tasks(apply: bool, mode: str, fallback: Optional[str]) -> dict:
    from coach.db import create_schema, learner_session
    from coach.tasks import (
        TaskModel,
        derive_step_tags,
        parse_parts,
        parse_tags,
        serialize_parts,
        serialize_tags,
    )
    from coach.taxonomy import validate

    create_schema()
    counts = {
        "seen": 0,
        "updated": 0,
        "dropped": 0,
        "unchanged": 0,
        "parts_retagged": 0,
        "secondary_removed": 0,
        "kept_unmapped": 0,
    }
    drops: list[tuple[str, str]] = []

    session = learner_session()
    try:
        from sqlalchemy import select

        models = list(session.scalars(select(TaskModel)))
        for m in models:
            counts["seen"] += 1
            old_block = parse_tags(m.tags_json)
            parts = parse_parts(m.parts_json)

            block_new, block_unmapped, removed = _retag(old_block, mode, fallback)
            counts["secondary_removed"] += removed

            new_parts = []
            part_unmapped: Optional[str] = None
            for p in parts:
                pnew, punmapped, premoved = _retag(p.get("tags"), mode, fallback)
                counts["secondary_removed"] += premoved
                if punmapped and not part_unmapped:
                    part_unmapped = punmapped
                if pnew is None and mode == "fallback":
                    pnew = {"primary": fallback, "secondary": []}
                if pnew is None:
                    pnew = p.get("tags") or {"primary": None, "secondary": []}
                if pnew.get("primary") != (p.get("tags") or {}).get("primary"):
                    counts["parts_retagged"] += 1
                p2 = dict(p)
                p2["tags"] = pnew
                new_parts.append(p2)

            critical_unmapped = part_unmapped if parts else block_unmapped

            if critical_unmapped and mode == "delete":
                counts["dropped"] += 1
                drops.append((m.id, critical_unmapped))
                continue

            if parts:
                # Block tags are a summary: re-derive from the mapped parts.
                final_tags = derive_step_tags(new_parts) or {
                    "primary": fallback or old_block.get("primary"),
                    "secondary": [],
                }
            elif block_new is not None:
                final_tags = block_new
            else:
                final_tags = old_block

            if critical_unmapped:
                counts["kept_unmapped"] += 1

            changed = final_tags != old_block or new_parts != parts
            if not changed:
                counts["unchanged"] += 1
                continue

            counts["updated"] += 1
            if not apply:
                continue

            if parts:
                # Validate before writing (skip for keep mode, which may be legacy).
                if mode != "keep":
                    validate(final_tags)
                m.parts_json = serialize_parts(new_parts)
                m.tags_json = serialize_tags(final_tags)
            else:
                if mode != "keep":
                    validate(final_tags)
                m.tags_json = serialize_tags(final_tags)

        if apply:
            session.commit()
            for task_id, _name in drops:
                from coach.tasks import delete_task

                delete_task(task_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    counts["drop_examples"] = drops[:10]
    return counts


def _merge_stats(rows: list[tuple[float, float, int]]) -> tuple[float, float, int]:
    """Merge own-observation Gaussian stats by count-weighted moments."""
    total_n = sum(max(0, int(n)) for _m, _v, n in rows)
    if total_n <= 0:
        m0, v0, _ = rows[0]
        return float(m0), float(v0), 0
    sum_nm = sum(int(n) * float(m) for m, _v, n in rows)
    sum_n2 = sum(int(n) * (float(v) + float(m) ** 2) for m, v, n in rows)
    mean = sum_nm / total_n
    var = max(0.0, sum_n2 / total_n - mean * mean)
    return mean, var, total_n


def migrate_beliefs(apply: bool) -> dict:
    """Rewrite legacy belief rows: ``tag`` → ``skill``; drop ``family`` rows."""
    from coach.db import create_schema, sqlite_conn
    from coach.taxonomy import is_node

    create_schema()
    counts = {"seen": 0, "dropped": 0, "rewritten": 0, "merged": 0, "unchanged": 0}

    with sqlite_conn() as conn:
        rows = conn.execute(
            "SELECT id, candidate, level, key, mean, variance, questions_answered "
            "FROM user_skill_beliefs"
        ).fetchall()

    delete_ids: list[str] = []
    groups: dict[tuple[str, str], list[tuple[float, float, int]]] = {}
    existing: dict[tuple[str, str], tuple[float, float, int]] = {}

    for rid, cand, level, key, mean, var, n in rows:
        counts["seen"] += 1
        if level == "global":
            counts["unchanged"] += 1
            continue
        if level == "tag":
            leaf = map_tag(key)
            if leaf is None:
                counts["dropped"] += 1
                delete_ids.append(rid)
                continue
            groups.setdefault((cand, leaf), []).append((float(mean or 0), float(var or 0), int(n or 0)))
            delete_ids.append(rid)
            continue
        if level in OLD_FAMILIES or level == "family":
            counts["dropped"] += 1
            delete_ids.append(rid)
            continue
        if level in ("domain", "area", "skill"):
            if is_node(key):
                existing[(cand, key)] = (float(mean or 0), float(var or 0), int(n or 0))
                counts["unchanged"] += 1
            else:
                counts["dropped"] += 1
                delete_ids.append(rid)
            continue
        counts["dropped"] += 1
        delete_ids.append(rid)

    upserts: list[tuple[str, str, float, float, int]] = []
    for (cand, leaf), stats in groups.items():
        base = list(stats)
        if (cand, leaf) in existing:
            base.append(existing[(cand, leaf)])
            counts["merged"] += 1
        mean, var, n = _merge_stats(base)
        upserts.append((cand, leaf, mean, var, n))
        counts["rewritten"] += 1

    if apply and (delete_ids or upserts):
        from uuid import uuid4

        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
        with sqlite_conn() as conn:
            for rid in delete_ids:
                conn.execute("DELETE FROM user_skill_beliefs WHERE id = ?", (rid,))
            for cand, leaf, mean, var, n in upserts:
                found = conn.execute(
                    "SELECT id FROM user_skill_beliefs WHERE candidate = ? AND level = 'skill' AND key = ?",
                    (cand, leaf),
                ).fetchone()
                if found:
                    conn.execute(
                        "UPDATE user_skill_beliefs SET mean = ?, variance = ?, questions_answered = ?, updated_at = ? "
                        "WHERE id = ?",
                        (mean, var, n, now, found[0]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO user_skill_beliefs "
                        "(id, candidate, level, key, mean, variance, questions_answered, updated_at) "
                        "VALUES (?, ?, 'skill', ?, ?, ?, ?, ?)",
                        (str(uuid4()), cand, leaf, mean, var, n, now),
                    )
            conn.commit()

    return counts


def drop_empty_sessions(apply: bool) -> dict:
    """Delete sessions that never received a scored answer.

    "Empty" means zero ``session_steps`` rows — a started-but-abandoned
    session. The session's separately-stored explanations are removed too, so
    no orphan rows remain. Dry-run by default; returns counters.
    """
    from coach.db import create_schema, sqlite_conn

    create_schema()
    counts = {"seen": 0, "empty": 0, "dropped": 0, "explanations_removed": 0}
    with sqlite_conn() as conn:
        step_counts = dict(
            conn.execute(
                "SELECT session_id, COUNT(*) FROM session_steps GROUP BY session_id"
            ).fetchall()
        )
        rows = conn.execute("SELECT session_id FROM active_sessions").fetchall()
        for (sid,) in rows:
            counts["seen"] += 1
            if step_counts.get(sid):
                continue
            counts["empty"] += 1
            if apply:
                # Delete on the *same* connection: opening a second
                # (ORM) connection while this one holds a transaction
                # deadlocks SQLite ("database is locked").
                cur = conn.execute(
                    "DELETE FROM explanations WHERE session_id = ?", (sid,)
                )
                counts["explanations_removed"] += cur.rowcount or 0
                conn.execute("DELETE FROM active_sessions WHERE session_id = ?", (sid,))
                counts["dropped"] += 1
        if apply:
            conn.commit()
    return counts


def migrate_sessions(apply: bool, mode: str, fallback: Optional[str], drop_empty: bool) -> dict:
    from coach.db import create_schema, sqlite_conn

    create_schema()
    dropped_empty = 0
    if drop_empty:
        dropped_empty = drop_empty_sessions(apply)["empty"]
    counts = {"seen": 0, "updated": 0, "dropped_empty": dropped_empty, "tasks_removed": 0}

    with sqlite_conn() as conn:
        rows = conn.execute("SELECT session_id, session_json FROM active_sessions").fetchall()
        for sid, raw in rows:
            counts["seen"] += 1
            try:
                parsed = json.loads(raw or "{}")
            except Exception:
                continue
            container = parsed.get("session") if isinstance(parsed, dict) and "session" in parsed else parsed
            if not isinstance(container, dict):
                continue
            tasks = container.get("tasks")
            if isinstance(tasks, list):
                kept = []
                for t in tasks:
                    if isinstance(t, dict) and not _remap_task(t, mode, fallback):
                        counts["tasks_removed"] += 1
                        continue
                    kept.append(t)
                if len(kept) != len(tasks):
                    container["tasks"] = kept
            new_raw = json.dumps(parsed)
            if new_raw != (raw or "{}"):
                counts["updated"] += 1
                if apply:
                    conn.execute(
                        "UPDATE active_sessions SET session_json = ? WHERE session_id = ?",
                        (new_raw, sid),
                    )
        if apply:
            conn.commit()
    return counts


def migrate_steps(apply: bool, mode: str, fallback: Optional[str]) -> dict:
    from coach.db import create_schema, sqlite_conn

    create_schema()
    counts = {"seen": 0, "updated": 0}
    with sqlite_conn() as conn:
        rows = conn.execute(
            "SELECT id, task_snapshot_json, state_before_json, state_after_json FROM session_steps"
        ).fetchall()
        for rid, snap_raw, before_raw, after_raw in rows:
            counts["seen"] += 1
            try:
                task = json.loads(snap_raw or "{}")
            except Exception:
                task = {}
            if isinstance(task, dict):
                _remap_task(task, "keep", fallback)  # historical: never drop a step
            new_state_before = _remap_json_state(before_raw)
            new_state_after = _remap_json_state(after_raw)
            snap = json.dumps(task)
            if apply and (snap != (snap_raw or "{}") or new_state_before or new_state_after):
                sets = ["task_snapshot_json = ?"]
                args: list = [snap]
                if new_state_before is not None:
                    sets.append("state_before_json = ?")
                    args.append(new_state_before)
                if new_state_after is not None:
                    sets.append("state_after_json = ?")
                    args.append(new_state_after)
                args.append(rid)
                conn.execute(f"UPDATE session_steps SET {', '.join(sets)} WHERE id = ?", args)
                counts["updated"] += 1
            elif snap != (snap_raw or "{}") or new_state_before or new_state_after:
                counts["updated"] += 1
        if apply:
            conn.commit()
    return counts


def _remap_json_state(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    new = map_state(parsed)
    if new is None or new == parsed:
        return None
    return json.dumps(new)


def run_migration(
    apply: bool, mode: str, fallback: Optional[str], drop_empty: bool, backup: bool = True
) -> dict:
    report: dict = {"apply": apply}
    if apply and backup:
        report["backup"] = backup_database()
    report["tasks"] = migrate_tasks(apply, mode, fallback)
    report["beliefs"] = migrate_beliefs(apply)
    report["sessions"] = migrate_sessions(apply, mode, fallback, drop_empty)
    report["steps"] = migrate_steps(apply, mode, fallback)
    return report


# ---------------------------------------------------------------------------
# delivery (step-by-step) migration
# ---------------------------------------------------------------------------


def _normalize_task_delivery(task: dict) -> bool:
    """Mutate a task dict into step-by-step delivery; return True if changed.

    Legacy migration only: a stored *snapshot* task with no ``parts`` is
    wrapped into a single part built from its task-level
    prompt/tags/max_score/difficulty. Live DB rows are wrapped by
    ``coach.db.create_schema`` before the legacy columns are dropped.
    ``delivery`` is forced to ``'phased'``.
    """
    changed = False
    parts = task.get("parts")
    if not isinstance(parts, list) or not parts:
        prompt = str(task.get("prompt") or "")
        m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(", prompt)
        key = m.group(1) if m else "solution"
        part = {
            "key": key,
            "prompt": prompt,
            "tags": task.get("tags") or {"primary": None, "secondary": []},
            "max_score": int(task.get("max_score") or 5),
            "difficulty": int(task.get("difficulty") or 2),
        }
        task["parts"] = [part]
        changed = True
    if task.get("delivery") != "phased":
        task["delivery"] = "phased"
        changed = True
    return changed


def migrate_delivery(apply: bool) -> dict:
    """Normalize the bank and stored snapshots to step-by-step delivery.

    Rewrites, in order: ``tasks`` rows (block → phased; row parts are already
    guaranteed by ``create_schema``), ``active_sessions`` task snapshots, and
    ``session_steps`` task snapshots (legacy partless snapshots become a
    single part). Task ids, owners, and attempt links are preserved.
    """
    from coach.db import create_schema, learner_session, sqlite_conn
    from coach.tasks import TaskModel, parse_parts, parse_tags, serialize_parts

    create_schema()
    counts = {
        "tasks_seen": 0,
        "tasks_updated": 0,
        "tasks_wrapped": 0,
        "sessions_seen": 0,
        "sessions_updated": 0,
        "steps_seen": 0,
        "steps_updated": 0,
    }

    # 1. The task bank.
    session = learner_session()
    try:
        from sqlalchemy import select

        models = list(session.scalars(select(TaskModel)))
        for m in models:
            counts["tasks_seen"] += 1
            task = {
                # Legacy partless rows still carry their prompt column so the
                # wrap below can build an implicit step from it.
                "prompt": getattr(m, "prompt", "") or "",
                "max_score": m.max_score,
                "difficulty": m.difficulty,
                "tags": parse_tags(m.tags_json),
                "delivery": m.delivery,
                "parts": parse_parts(m.parts_json),
            }
            had_parts = bool(task["parts"])
            if not _normalize_task_delivery(task):
                continue
            if not had_parts:
                counts["tasks_wrapped"] += 1
            counts["tasks_updated"] += 1
            if apply:
                m.parts_json = serialize_parts(task["parts"])
                m.delivery = "phased"
        if apply:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    with sqlite_conn() as conn:
        # 2. In-flight session task snapshots.
        for sid, raw in conn.execute(
            "SELECT session_id, session_json FROM active_sessions"
        ).fetchall():
            counts["sessions_seen"] += 1
            try:
                parsed = json.loads(raw or "{}")
            except Exception:
                continue
            container = (
                parsed.get("session")
                if isinstance(parsed, dict) and "session" in parsed
                else parsed
            )
            if not isinstance(container, dict):
                continue
            changed = False
            for t in container.get("tasks") or []:
                if isinstance(t, dict) and _normalize_task_delivery(t):
                    changed = True
            if changed:
                counts["sessions_updated"] += 1
                if apply:
                    conn.execute(
                        "UPDATE active_sessions SET session_json = ? WHERE session_id = ?",
                        (json.dumps(parsed), sid),
                    )

        # 3. Historical step snapshots (review display).
        for rid, snap_raw in conn.execute(
            "SELECT id, task_snapshot_json FROM session_steps"
        ).fetchall():
            counts["steps_seen"] += 1
            try:
                task = json.loads(snap_raw or "{}")
            except Exception:
                continue
            if not isinstance(task, dict):
                continue
            if _normalize_task_delivery(task):
                counts["steps_updated"] += 1
                if apply:
                    conn.execute(
                        "UPDATE session_steps SET task_snapshot_json = ? WHERE id = ?",
                        (json.dumps(task), rid),
                    )
        if apply:
            conn.commit()

    return counts


# ---------------------------------------------------------------------------
# coverage report
# ---------------------------------------------------------------------------


def coverage_report() -> dict:
    from sqlalchemy import select

    from coach.db import create_schema, learner_session
    from coach.tasks import TaskModel, parse_parts, parse_tags
    from coach.taxonomy import LEAF_NODES

    create_schema()
    session = learner_session()
    try:
        models = list(session.scalars(select(TaskModel)))
    finally:
        session.close()

    counts: dict[str, int] = {leaf: 0 for leaf in LEAF_NODES}
    for m in models:
        tags = parse_tags(m.tags_json)
        for name in [tags.get("primary"), *(tags.get("secondary") or [])]:
            if name in counts:
                counts[name] += 1
        for p in parse_parts(m.parts_json):
            for name in [(p.get("tags") or {}).get("primary"), *((p.get("tags") or {}).get("secondary") or [])]:
                if name in counts:
                    counts[name] += 1
    covered = [leaf for leaf, n in counts.items() if n > 0]
    uncovered = [leaf for leaf, n in counts.items() if n == 0]
    return {"tasks": len(models), "covered": covered, "uncovered": uncovered, "counts": counts}


# ---------------------------------------------------------------------------
# hygiene report (read-only)
# ---------------------------------------------------------------------------


def hygiene_report() -> dict:
    """Audit the task bank for learner-facing scaffold hygiene.

    Flags steps with no starter code and starter code that gives the answer
    away by declaring private members or instance state. Read-only, like
    ``coverage``: it never rewrites author text.
    """
    from sqlalchemy import select

    from coach.db import create_schema, learner_session
    from coach.tasks import TaskModel, task_to_dict

    create_schema()
    session = learner_session()
    try:
        models = list(session.scalars(select(TaskModel)))
    finally:
        session.close()

    private_section = re.compile(r"(^|\n)\s*(private|protected)\s*:")
    member_field = re.compile(r"(^|\n)\s*(?:mutable\s+)?[\w:<>,\s*&]+\s+\w+_\s*(?:=|;)")
    self_attr = re.compile(r"(^|\n)\s*self\.\w+\s*=")
    comment = re.compile(r"//|/\*|#")

    counts = {
        "scaffold_leaks_internals": 0,
        "scaffold_missing_comments": 0,
        "scaffold_missing": 0,
    }
    findings: list[dict] = []
    for model in models:
        task = task_to_dict(model)
        parts = task.get("parts") or []
        for part in parts:
            # Audit every declared language's starter code (multi-language
            # tasks carry a ``scaffolds`` map; single-language tasks a
            # ``scaffold`` string).
            default_lang = task.get("language") or "python"
            scaffolds = part.get("scaffolds") if isinstance(part.get("scaffolds"), dict) else {}
            if not scaffolds:
                scaffolds = {default_lang: part.get("scaffold") or ""}
            for language, scaffold in scaffolds.items():
                if not str(scaffold or "").strip():
                    counts["scaffold_missing"] += 1
                    findings.append(
                        {
                            "task_id": task["id"],
                            "owner": task.get("owner"),
                            "issue": "scaffold_missing",
                            "part_key": part.get("key"),
                            "language": language,
                            "detail": "Step has no starter code.",
                        }
                    )
                    continue
                leaks: list[str] = []
                if private_section.search(scaffold):
                    leaks.append("private/protected section")
                if member_field.search(scaffold):
                    leaks.append("member field")
                if self_attr.search(scaffold):
                    leaks.append("instance attribute")
                if leaks:
                    counts["scaffold_leaks_internals"] += 1
                    findings.append(
                        {
                            "task_id": task["id"],
                            "owner": task.get("owner"),
                            "issue": "scaffold_leaks_internals",
                            "part_key": part.get("key"),
                            "language": language,
                            "detail": "; ".join(leaks),
                        }
                    )
                if ("class " in scaffold or "def " in scaffold) and not comment.search(scaffold):
                    counts["scaffold_missing_comments"] += 1
                    findings.append(
                        {
                            "task_id": task["id"],
                            "owner": task.get("owner"),
                            "issue": "scaffold_missing_comments",
                            "part_key": part.get("key"),
                            "language": language,
                            "detail": "Starter code has API surface but no comments.",
                        }
                    )
    return {"tasks": len(models), "findings": findings, "counts": counts}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print(obj: dict) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="coach.migrate", description=__doc__.splitlines()[0])
    parser.add_argument(
        "command",
        nargs="?",
        default="migrate",
        choices=["migrate", "coverage", "delivery", "hygiene", "sessions"],
        help="migrate (default) | coverage | delivery | hygiene | sessions",
    )
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument(
        "--on-unmapped",
        choices=["delete", "fallback", "keep"],
        default="delete",
        help="policy for tags with no current counterpart",
    )
    parser.add_argument("--fallback", default=None, help="leaf skill for --on-unmapped fallback")
    parser.add_argument("--no-backup", action="store_true", help="skip the pre-apply DB backup")
    parser.add_argument(
        "--keep-empty-sessions",
        dest="drop_empty_sessions",
        action="store_false",
        help="retain active sessions that have no recorded steps",
    )
    parser.set_defaults(drop_empty_sessions=True)

    args = parser.parse_args(argv)

    if args.command == "coverage":
        _print(coverage_report())
        return 0

    if args.command == "hygiene":
        _print(hygiene_report())
        return 0

    if args.command == "delivery":
        report: dict = {"apply": args.apply}
        if args.apply and not args.no_backup:
            report["backup"] = backup_database()
        report["delivery"] = migrate_delivery(args.apply)
        _print(report)
        return 0

    if args.command == "sessions":
        report = {"apply": args.apply}
        if args.apply and not args.no_backup:
            report["backup"] = backup_database()
        report["sessions"] = drop_empty_sessions(args.apply)
        _print(report)
        return 0

    fallback = args.fallback
    if args.on_unmapped == "fallback":
        from coach.taxonomy import is_leaf

        if not is_leaf(fallback):
            print("error: --fallback must be a leaf skill from coach.taxonomy", file=sys.stderr)
            return 2

    if args.apply and args.no_backup:
        _print(run_migration(True, args.on_unmapped, fallback, args.drop_empty_sessions, backup=False))
        return 0

    _print(run_migration(args.apply, args.on_unmapped, fallback, args.drop_empty_sessions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
