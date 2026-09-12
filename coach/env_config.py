"""Single source of truth for environment-variable validation.

Secrets/credentials live in a gitignored ``.env`` file for local dev (see
``.env.example``) or in real environment variables / a platform secret manager
in production. Nothing here reads secret *values* — it only checks presence
and shape, so it is safe to run in tests and CI.

``validate_env`` is pure (takes a mapping) so it is unit-testable.
``ensure_env_checked`` logs warnings in dev/test and raises in production
(``APP_ENV=production``) when required config is missing or insecure.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Mapping

log = logging.getLogger(__name__)

REQUIRED = ["GOOGLE_API_KEY"]
OAUTH_PAIR = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
NUMERIC_VARS = ("EVAL_RETRY_ATTEMPTS", "EVAL_RETRY_INITIAL_DELAY", "EVAL_RETRY_MAX_DELAY")


@dataclass
class EnvStatus:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _get(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def validate_env(env: Mapping[str, str] | None = None) -> EnvStatus:
    """Check env config. Never raises; returns errors + warnings."""
    env = env if env is not None else os.environ
    status = EnvStatus()

    for key in REQUIRED:
        if not _get(env, key):
            status.errors.append(
                f"Missing required {key}. Copy .env.example to .env "
                "or set it in your environment / secret manager."
            )

    oauth_set = [_get(env, k) for k in OAUTH_PAIR]
    if any(oauth_set) and not all(oauth_set):
        missing = [k for k, v in zip(OAUTH_PAIR, oauth_set) if not v]
        status.warnings.append(
            f"Partial Google OAuth config (missing {', '.join(missing)}). "
            "Login is disabled until BOTH GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET are set."
        )

    for key in NUMERIC_VARS:
        raw = _get(env, key)
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            status.errors.append(f"{key} must be numeric, got {raw!r}.")
            continue
        if value <= 0:
            status.errors.append(f"{key} must be > 0, got {raw!r}.")

    app_env = _get(env, "APP_ENV").lower()
    frontend = _get(env, "FRONTEND_URL").lower()
    cors = _get(env, "CORS_ORIGINS")
    if app_env == "production":
        if not frontend or "localhost" in frontend or frontend.startswith("http://"):
            status.warnings.append(
                "APP_ENV=production but FRONTEND_URL is unset, localhost, "
                "or plain http. Set the public https frontend URL."
            )
        if "*" in cors:
            status.warnings.append(
                "CORS_ORIGINS contains '*', which allows any origin with "
                "credentials. Restrict it to the public frontend URL."
            )
    return status


def ensure_env_checked(env: Mapping[str, str] | None = None) -> EnvStatus:
    """Log warnings; raise RuntimeError on errors only in production.

    Dev/test stay bootable without keys (tests use fake judges), while
    ``APP_ENV=production`` fails fast instead of serving a broken app.
    """
    env = env if env is not None else os.environ
    status = validate_env(env)
    for warning in status.warnings:
        log.warning("env: %s", warning)
    if status.errors:
        first = status.errors[0]
        if _get(env, "APP_ENV").lower() == "production":
            raise RuntimeError(f"Invalid environment config: {first}")
        log.warning("env: %s", first)
    return status
