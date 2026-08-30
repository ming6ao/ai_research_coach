"""Google OAuth 2.0 (authorization-code flow) using stdlib only.

Server-side redirect flow:

  /api/auth/google/url       -> returns Google's authorization URL (with state)
  user signs in on Google    -> browser redirects to /api/auth/google/callback
  callback exchanges code    -> fetches userinfo -> issues our bearer token ->
                                redirects the browser to FRONTEND_URL/?token=...

Config via environment:
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET  (required)
  GOOGLE_REDIRECT_URI  (default http://localhost:8001/api/auth/google/callback)
  FRONTEND_URL         (default http://localhost:5173)
"""

import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPE = "openid email profile"
STATE_TTL_SECONDS = 600

# Pending OAuth states (state -> expiry timestamp). In-memory is fine for the
# single-process development server.
_pending_states: dict[str, float] = {}
_states_lock = threading.Lock()


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
    with _states_lock:
        _pending_states[state] = time.time() + STATE_TTL_SECONDS
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
    with _states_lock:
        ts = _pending_states.pop(state, None)
        if ts is None or time.time() > ts:
            return False
    return True


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