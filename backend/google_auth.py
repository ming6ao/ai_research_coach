"""Google OAuth 2.0 (authorization-code flow) using stdlib only.

Server-side redirect flow:

  /api/auth/google/url       -> returns Google's authorization URL (with state)
  user signs in on Google    -> browser redirects to /api/auth/google/callback
  callback exchanges code    -> fetches userinfo -> issues our bearer token ->
                                sets the HttpOnly session cookie and redirects
                                the browser to FRONTEND_URL/?login=success

Config via environment:
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET  (required)
  GOOGLE_REDIRECT_URI  (default http://localhost:8001/api/auth/google/callback)
  FRONTEND_URL         (default http://localhost:5173)

OAuth ``state`` values are stored in the shared SQLite database
(``oauth_states`` table), so the flow works across multiple server workers.
States are single-use and expire after 10 minutes.
"""

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPE = "openid email profile"
STATE_TTL_SECONDS = 600


def _connect():
    from coach.db import sqlite_conn

    return sqlite_conn()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _client_config() -> dict:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set to enable Google login."
        )
    return {"client_id": client_id, "client_secret": client_secret}


def redirect_uri() -> str:
    return os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8001/api/auth/google/callback"
    ).strip()


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:5173").strip()


def new_authorization_url() -> tuple[str, str]:
    """Build Google's authorization URL. Returns (url, state)."""
    cfg = _client_config()
    state = secrets.token_urlsafe(24)
    expires = (_utcnow() + timedelta(seconds=STATE_TTL_SECONDS)).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO oauth_states (state, expires_at) VALUES (?, ?)",
            (state, expires),
        )
        # Opportunistic cleanup of expired states.
        conn.execute(
            "DELETE FROM oauth_states WHERE expires_at <= ?",
            (_utcnow().isoformat(),),
        )
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}", state


def consume_state(state: str) -> bool:
    """Verify and consume a one-time OAuth state. Returns False if unknown/expired."""
    if not state:
        return False
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM oauth_states WHERE state = ? AND expires_at > ?",
            (state, _utcnow().isoformat()),
        )
        return cur.rowcount > 0


def exchange_code(code: str) -> dict:
    """Exchange the authorization code for tokens. Raises ValueError on failure."""
    cfg = _client_config()
    data = {
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
    }
    payload = _post_form(GOOGLE_TOKEN_URL, data)
    if "access_token" not in payload:
        raise ValueError("Google token exchange returned no access token.")
    return payload


def fetch_userinfo(access_token: str) -> dict:
    """Fetch the signed-in user's profile. Raises ValueError on failure."""
    return _get_json(GOOGLE_USERINFO_URL, {"Authorization": f"Bearer {access_token}"})


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    return _open(req)


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    return _open(req)


def _open(req) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise ValueError(f"Google API error {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        raise ValueError(f"Google API unreachable: {e.reason}")