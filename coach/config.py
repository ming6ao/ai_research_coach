import os

MODEL = os.getenv("EVAL_MODEL", "gemini-3.5-flash-lite")

RETRYABLE_STATUS = (408, 429, 500, 502, 503, 504)
RETRY_ATTEMPTS = int(os.getenv("EVAL_RETRY_ATTEMPTS", "5"))
RETRY_INITIAL_DELAY = float(os.getenv("EVAL_RETRY_INITIAL_DELAY", "1.0"))
RETRY_MAX_DELAY = float(os.getenv("EVAL_RETRY_MAX_DELAY", "30.0"))

# --- Step-by-step task delivery ------------------------------------------
# Every task is delivered step-by-step: its ``parts`` are shown one at a
# time, each starting from its own scaffold. Delivery always advances
# to the next step after each submission, regardless of the score — the
# learner sees every step and reviews the coaching for each one. Each step's
# ``pass_score`` is still authored/defaulted below as metadata, but it no
# longer gates advancement.
PHASE_PASS_FRACTION = float(os.getenv("PHASE_PASS_FRACTION", "0.7"))
# Retained for backward compatibility; no longer caps attempts.
PHASE_MAX_ATTEMPTS = int(os.getenv("PHASE_MAX_ATTEMPTS", "3"))


def default_pass_score(max_score: int) -> int:
    """Default per-step target score (authored metadata; not an advance gate)."""
    try:
        max_score = int(max_score)
    except (TypeError, ValueError):
        max_score = 5
    return max(1, round(PHASE_PASS_FRACTION * max(1, max_score)))


def http_retry_options():
    from google.genai import types

    return types.HttpRetryOptions(
        attempts=RETRY_ATTEMPTS,
        initial_delay=RETRY_INITIAL_DELAY,
        max_delay=RETRY_MAX_DELAY,
        exp_base=2.0,
        jitter=1.0,
        http_status_codes=list(RETRYABLE_STATUS),
    )
