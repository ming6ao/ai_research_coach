"""Authentication + ownership tests.

Covers Google OAuth login, bearer-token identity, and the ownership rule that
sessions are scoped to their candidate (guest or signed-in) with a single
unified coaching path for both.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import backend.google_auth as google_auth
import coach.db as db
from coach.judge import EvaluationResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbfile = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", dbfile)
    from coach.tasks import create_task as _seed_task

    _seed_task(
        prompt="Seed task for auth tests. Signature: def f():",
        owner="bank@example.com",
        difficulty=2,
        max_score=5,
        source="user",
        is_public=True,
        tags={"primary": "testing"},
        task_id="seed_auth_01",
    )
    from backend.main import app
    return TestClient(app)


@pytest.fixture
def google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")


@pytest.fixture
def fake_google(monkeypatch):
    def exchange_code(code):
        return {"access_token": "fake-access", "id_token": "fake-id"}

    def fetch_userinfo(access_token):
        return {"id": "google-user-1", "email": "user@example.com", "name": "Test User"}

    monkeypatch.setattr(google_auth, "exchange_code", exchange_code)
    monkeypatch.setattr(google_auth, "fetch_userinfo", fetch_userinfo)


@pytest.fixture
def fake_judge(monkeypatch):
    from coach import judge as judge_mod
    from coach.judge import CoachContent, CoachStep

    class FakeJudge:
        def evaluate(self, task, answer, previous_code=None):
            from coach.judge import score_targets

            targets = score_targets(task)
            parts = [
                {"key": p["key"], "score": float(p["max_score"]), "rationale": "Perfect part."}
                for p in targets
            ]
            max_score = sum(int(p["max_score"]) for p in targets)
            coach = CoachContent(
                feedback="Great job!",
                misconception="No misconception.",
                steps=[CoachStep("Done", "The solution is correct.", None)],
            )
            result = EvaluationResult(
                task["id"], max_score, max_score, "Perfect.", coach.to_dict(), parts
            )
            return result, coach

    monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _login_via_callback(client) -> None:
    """Complete a fake Google login; the session cookie lands in the client's jar."""
    res = client.get("/api/auth/google/url")
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]
    cb = client.get("/api/auth/google/callback", params={"code": "auth-code", "state": state},
                    follow_redirects=False)
    assert cb.status_code == 303
    return cb


def test_google_auth_url_requires_config(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    res = client.get("/api/auth/google/url")
    assert res.status_code == 500
    assert "GOOGLE_CLIENT_ID" in res.json()["detail"]


def test_google_auth_url_returns_url(client, google_env):
    res = client.get("/api/auth/google/url")
    assert res.status_code == 200
    url = res.json()["url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-client-id" in url


def test_google_callback_sets_cookie_and_redirects(client, google_env, fake_google):
    # Get a real state first so the callback can consume it.
    res = client.get("/api/auth/google/url")
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]

    cb = client.get("/api/auth/google/callback", params={"code": "auth-code", "state": state},
                    follow_redirects=False)
    assert cb.status_code == 303
    # No token in the URL (stays out of logs/history); non-sensitive flag only.
    assert cb.headers["location"] == "http://localhost:5173/?login=success"
    assert "token=" not in cb.headers["location"]
    set_cookie = cb.headers.get("set-cookie", "")
    assert "ai_coach_token=" in set_cookie
    assert "httponly" in set_cookie.lower()

    # The stored cookie authenticates without any Authorization header.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "user@example.com"
    assert me.json()["user"]["display_name"] == "Test User"


def test_google_callback_state_is_single_use(client, google_env, fake_google):
    res = client.get("/api/auth/google/url")
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]

    first = client.get("/api/auth/google/callback", params={"code": "c", "state": state},
                       follow_redirects=False)
    assert first.status_code == 303

    second = client.get("/api/auth/google/callback", params={"code": "c", "state": state},
                        follow_redirects=False)
    assert second.status_code == 400


def test_oauth_state_expires(client, google_env):
    import backend.google_auth as google_auth_mod

    res = client.get("/api/auth/google/url")
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]
    with db.sqlite_conn() as conn:
        conn.execute(
            "UPDATE oauth_states SET expires_at = ? WHERE state = ?",
            ("2000-01-01T00:00:00+00:00", state),
        )
    assert google_auth_mod.consume_state(state) is False


def test_google_callback_bad_state(client, google_env, fake_google):
    cb = client.get("/api/auth/google/callback", params={"code": "c", "state": "nope"},
                    follow_redirects=False)
    assert cb.status_code == 400


def test_google_callback_reuses_existing_user(client, google_env, fake_google):
    for _ in range(2):
        _login_via_callback(client)

    with auth._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users WHERE email = 'user@example.com'").fetchone()[0]
    assert count == 1


def test_google_callback_requires_email(client, google_env, monkeypatch):
    monkeypatch.setattr(google_auth, "exchange_code", lambda code: {"access_token": "x"})
    monkeypatch.setattr(google_auth, "fetch_userinfo", lambda token: {"id": "x", "name": "No Email"})

    res = client.get("/api/auth/google/url")
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]
    cb = client.get("/api/auth/google/callback", params={"code": "c", "state": state},
                    follow_redirects=False)
    assert cb.status_code == 400
    assert "no email" in cb.json()["detail"]


def test_logout_revokes_token(client, google_env):
    user = auth.upsert_google_user("u@example.com", "U")
    token = auth.create_token(user["id"])

    assert client.get("/api/auth/me", headers=_auth_headers(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=_auth_headers(token)).status_code == 200
    assert client.get("/api/auth/me", headers=_auth_headers(token)).status_code == 401


def test_cookie_logout_clears_session(client, google_env, fake_google):
    _login_via_callback(client)
    assert client.get("/api/auth/me").status_code == 200

    # Cookie-authenticated logout (no Bearer header, browser-like Origin).
    assert client.post("/api/auth/logout", headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_csrf_blocks_cookie_writes_without_origin(client, google_env, fake_google, fake_judge):
    _login_via_callback(client)

    # Cookie present, unsafe method, no Origin -> forged request rejected.
    assert client.post("/api/v1/sessions", json={}).status_code == 403

    # Matching Origin -> allowed.
    ok = client.post("/api/v1/sessions", json={}, headers={"Origin": "http://localhost:5173"})
    assert ok.status_code == 201

    # Foreign Origin -> rejected.
    assert client.post("/api/v1/sessions", json={}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_csrf_skips_bearer_and_guests(client, google_env, fake_judge):
    user = auth.upsert_google_user("csrf@b.co", "Csrf")
    token = auth.create_token(user["id"])

    # Bearer callers carry no forgeable credential -> no Origin needed.
    assert client.post("/api/v1/sessions", json={}, headers=_auth_headers(token)).status_code == 201

    # Guests send no session cookie -> nothing to forge.
    assert client.post("/api/v1/sessions", json={}).status_code == 201


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_guest_start_creates_guest_candidate(client):
    res = client.post("/api/v1/sessions", json={})
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["candidate"].startswith("guest-")
    assert data["current_task"] is not None


def test_guest_submit_is_scored(client, fake_judge):
    started = client.post("/api/v1/sessions", json={})
    sid = started.json()["data"]["id"]
    task_id = started.json()["data"]["current_task"]["id"]

    res = client.post(f"/api/v1/sessions/{sid}/answers", json={"task_id": task_id, "answer": "def f(): pass"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["coach"]["feedback"] == "Great job!"
    assert data["ability_update"] is not None


def test_authenticated_start_uses_account(client, google_env):
    user = auth.upsert_google_user("alice@b.co", "Alice")
    token = auth.create_token(user["id"])

    res = client.post("/api/v1/sessions", json={}, headers=_auth_headers(token))
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["candidate"] == "alice@b.co"


def test_sessions_are_scoped_to_account(client, google_env):
    user = auth.upsert_google_user("bob@b.co", "Bob")
    token = auth.create_token(user["id"])
    client.post("/api/v1/sessions", json={}, headers=_auth_headers(token))

    mine = client.get("/api/v1/me/sessions", headers=_auth_headers(token))
    assert mine.status_code == 200
    sessions = mine.json()["data"]
    assert len(sessions) == 1
    assert sessions[0]["done"] is False
    assert "score" not in sessions[0]

    guest = client.get("/api/v1/me/sessions")
    assert guest.status_code == 200
    assert guest.json()["data"] == []


def test_guest_cannot_open_named_session(client, google_env):
    user = auth.upsert_google_user("carol@b.co", "Carol")
    token = auth.create_token(user["id"])
    started = client.post("/api/v1/sessions", json={}, headers=_auth_headers(token))
    sid = started.json()["data"]["id"]

    guest_open = client.get(f"/api/v1/sessions/{sid}")
    assert guest_open.status_code == 403
    assert "own sessions" in guest_open.json()["detail"]


def test_guest_can_reopen_own_session(client):
    started = client.post("/api/v1/sessions", json={})
    sid = started.json()["data"]["id"]

    reopen = client.get(f"/api/v1/sessions/{sid}")
    assert reopen.status_code == 200
    assert reopen.json()["data"]["candidate"].startswith("guest-")


def test_user_can_delete_own_data(client, google_env):
    user = auth.upsert_google_user("erin@b.co", "Erin")
    token = auth.create_token(user["id"])
    client.post("/api/v1/sessions", json={}, headers=_auth_headers(token))

    res = client.delete("/api/v1/me/data", headers=_auth_headers(token))
    assert res.status_code == 200
    assert res.json()["data"]["deleted"] > 0

    mine = client.get("/api/v1/me/sessions", headers=_auth_headers(token))
    assert mine.json()["data"] == []
    assert client.get("/api/v1/me", headers=_auth_headers(token)).status_code == 200
    assert client.get("/api/v1/me").status_code == 401