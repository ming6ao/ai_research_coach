"""Adaptive hint selection for coding tasks.

Each task may declare an ordered list of hints. A hint is *pre-revealed* with
the task when the candidate's estimated ability for that skill is below the
hint's `reveal_threshold`; otherwise it stays hidden and can be requested on
demand. Only hints the candidate actually views/requests reduce the effective
score (see core.score.effective_score).
"""

from core.score import DEFAULT_HINT_WEIGHT


def select_hints(task: dict, ability_mean: float) -> list[dict]:
    """Return the task's hints annotated with whether they are pre-revealed.

    Each returned item is:
        {"id", "text", "weight", "pre_revealed": bool}

    Hints without a `reveal_threshold` are never pre-revealed (requestable on
    demand). Reveal thresholds are expected to be ordered gentlest -> strongest.
    """
    selected = []
    for hint in task.get("hints", []):
        threshold = hint.get("reveal_threshold")
        pre_revealed = threshold is not None and ability_mean < threshold
        selected.append(
            {
                "id": hint["id"],
                "text": hint["text"],
                "weight": hint.get("weight", DEFAULT_HINT_WEIGHT),
                "pre_revealed": pre_revealed,
            }
        )
    return selected


def hint_penalty(task: dict, viewed_ids) -> float:
    """Total mastery penalty for the hints with the given ids.

    Only ids that actually exist on the task contribute, so a caller can pass
    whatever ids were viewed without worrying about unknown/malicious ids.
    """
    by_id = {
        hint["id"]: hint.get("weight", DEFAULT_HINT_WEIGHT)
        for hint in task.get("hints", [])
    }
    return sum(by_id.get(hid, 0.0) for hid in viewed_ids)


def next_hidden_hint(task: dict, viewed_ids, ability_mean: float = None) -> dict | None:
    """Return the first hint not yet viewed and not pre-revealed, or None.

    When `ability_mean` is provided, hints whose `reveal_threshold` is above
    the ability are already pre-revealed with the task, so they are skipped.
    """
    for hint in task.get("hints", []):
        if hint["id"] in viewed_ids:
            continue
        threshold = hint.get("reveal_threshold")
        if ability_mean is not None and threshold is not None and ability_mean < threshold:
            continue
        return hint
    return None