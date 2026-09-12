"""User accounts and bearer-token authentication (stdlib only).

Users are created through Google OAuth (see backend/google_auth.py): after a
Google account is verified, `upsert_google_user` creates or reuses a local user
row (keyed by email) and this module issues a random bearer token with a 30-day
expiry. Tokens are stored in the same SQLite database as the rest of the app.
"""

import sqlite3
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

from coach.db import sqlite_conn

TOKEN_TTL_DAYS = 30

# Cookie name for browser-based auth (Phase 1: read-only fallback for the
# Authorization header; Phase 3 will set it in the OAuth callback).
AUTH_COOKIE_NAME = "ai_coach_token"


def admin_emails() -> set[str]:
    """Parse ADMIN_EMAILS (comma-separated) into a lowercase email set."""
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin(user: Optional[dict]) -> bool:
    """True when the user's email is on the ADMIN_EMAILS allowlist."""
    if not user:
        return False
    email = (user.get("email") or "").strip().lower()
    return bool(email) and email in admin_emails()


def _connect() -> sqlite3.Connection:
    return sqlite_conn()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_google_user(email: str, name: str) -> dict:
    """Create or update the local user for a verified Google account.

    Identity is keyed by email. Returns the user dict.
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("Google account has no email.")
    now = _utcnow().isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, display_name FROM users WHERE email = ?", (email,)
        ).fetchone()
        if row is None:
            uid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO users (id, email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?, ?)",
                (uid, email, "oauth:google", (name or "").strip(), now),
            )
            return {"id": uid, "email": email, "display_name": (name or "").strip()}
        conn.execute(
            "UPDATE users SET display_name = ? WHERE id = ?", ((name or "").strip(), row[0])
        )
        return {"id": row[0], "email": row[1], "display_name": (name or row[2]) or ""}


def create_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    expires = now + timedelta(days=TOKEN_TTL_DAYS)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
    return token


def revoke_token(token: str):
    with _connect() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))


def user_from_token(token: str) -> Optional[dict]:
    """Resolve a bearer token to a user dict, or None if invalid/expired."""
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.display_name
            FROM auth_tokens t JOIN users u ON u.id = t.user_id
            WHERE t.token = ? AND t.expires_at > ?
            """,
            (token, _utcnow().isoformat()),
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "email": row[1], "display_name": row[2]}


def get_current_user(request: Request) -> Optional[dict]:
    """FastAPI dependency: authenticated user or None (guests allowed).

    Reads the ``Authorization: Bearer`` header first, then falls back to the
    ``ai_coach_token`` HttpOnly cookie (set by the OAuth callback in Phase 3).
    Kept for backward compatibility; prefer :func:`get_optional_user`.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return user_from_token(auth[len("Bearer "):].strip())
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "")
    if cookie_token:
        return user_from_token(cookie_token.strip())
    return None


def get_optional_user(request: Request) -> Optional[dict]:
    """Alias for :func:`get_current_user` — guests allowed (returns None)."""
    return get_current_user(request)


def require_user(request: Request) -> dict:
    """FastAPI dependency: authenticated user or 401 (no guest fallback)."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user