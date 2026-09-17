import os

MODEL = os.getenv("EVAL_MODEL", "gemini-3.5-flash-lite")

RETRYABLE_STATUS = (408, 429, 500, 502, 503, 504)
RETRY_ATTEMPTS = int(os.getenv("EVAL_RETRY_ATTEMPTS", "5"))
RETRY_INITIAL_DELAY = float(os.getenv("EVAL_RETRY_INITIAL_DELAY", "1.0"))
RETRY_MAX_DELAY = float(os.getenv("EVAL_RETRY_MAX_DELAY", "30.0"))

# --- Step-by-step task delivery ------------------------------------------
# Every task is delivered step-by-step: its ``parts`` are shown one at a
# time, each pass-gated, with the candidate's code carried forward. A step
# advances once its score reaches ``pass_score``
# (default ``round(PHASE_PASS_FRACTION * max_score)``) or after
# ``PHASE_MAX_ATTEMPTS`` attempts, whichever comes first.
PHASE_PASS_FRACTION = float(os.getenv("PHASE_PASS_FRACTION", "0.7"))
PHASE_MAX_ATTEMPTS = int(os.getenv("PHASE_MAX_ATTEMPTS", "3"))


def default_pass_score(max_score: int) -> int:
    """Default score required to advance a phase (at least 1)."""
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
