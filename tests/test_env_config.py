"""Unit tests for coach/env_config.py (pure mapping-based validation)."""

import pytest

from coach.env_config import ensure_env_checked, validate_env


def _base_env(**overrides):
    env = {
        "GOOGLE_API_KEY": "test-key",
        "GOOGLE_CLIENT_ID": "cid",
        "GOOGLE_CLIENT_SECRET": "csecret",
        "APP_ENV": "development",
    }
    env.update(overrides)
    return env


def test_valid_env_has_no_errors_or_warnings():
    assert validate_env(_base_env()).ok


def test_missing_api_key_is_error():
    status = validate_env(_base_env(GOOGLE_API_KEY=""))
    assert not status.ok
    assert any("GOOGLE_API_KEY" in e for e in status.errors)


def test_partial_oauth_is_warning_not_error():
    status = validate_env(_base_env(GOOGLE_CLIENT_SECRET=""))
    assert status.ok
    assert any("GOOGLE_CLIENT_SECRET" in w for w in status.warnings)


def test_neither_oauth_var_is_fine():
    env = _base_env(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    assert validate_env(env).ok


def test_bad_numeric_is_error():
    status = validate_env(_base_env(EVAL_RETRY_ATTEMPTS="abc"))
    assert not status.ok


def test_nonpositive_numeric_is_error():
    status = validate_env(_base_env(EVAL_RETRY_ATTEMPTS="0"))
    assert not status.ok


def test_production_warns_on_localhost_frontend():
    env = _base_env(APP_ENV="production", FRONTEND_URL="http://localhost:5173")
    status = validate_env(env)
    assert status.ok  # warning only, bootable
    assert any("FRONTEND_URL" in w for w in status.warnings)


def test_production_warns_on_wildcard_cors():
    env = _base_env(
        APP_ENV="production",
        FRONTEND_URL="https://coach.example.com",
        CORS_ORIGINS="*",
    )
    assert any("CORS_ORIGINS" in w for w in validate_env(env).warnings)


def test_ensure_warns_in_dev_but_raises_in_production():
    ensure_env_checked(_base_env(GOOGLE_API_KEY=""))  # dev: no raise
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        ensure_env_checked(_base_env(GOOGLE_API_KEY="", APP_ENV="production"))
