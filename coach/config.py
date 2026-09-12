import os

MODEL = os.getenv("EVAL_MODEL", "gemini-3.5-flash-lite")

RETRYABLE_STATUS = (408, 429, 500, 502, 503, 504)
RETRY_ATTEMPTS = int(os.getenv("EVAL_RETRY_ATTEMPTS", "5"))
RETRY_INITIAL_DELAY = float(os.getenv("EVAL_RETRY_INITIAL_DELAY", "1.0"))
RETRY_MAX_DELAY = float(os.getenv("EVAL_RETRY_MAX_DELAY", "30.0"))


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
