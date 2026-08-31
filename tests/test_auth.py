"""Authentication + guest/practice enforcement tests.

Covers Google OAuth login, bearer-token identity, and the backend rule that
scored assessments require a logged-in account while guests are limited to
practice mode.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import backend.google_auth as google_auth
import backend.dependencies as deps
import core.storage as storage
from evaluators.base import EvaluationResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr(auth, "DB_PATH", db)
    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(storage, "DB_PATH", db)
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
    from evaluators import judge as judge_mod

    class FakeJudge:
        def evaluate(self, task, answer):
            max_score = task.get("max_score", 5)
            result = EvaluationResult(task["id"], task["skill"], max_score, max_score, "Perfect.")
            return result, "Great job!"

    monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _token_from_redirect(res) -> str:
    loc = res.headers["location"]
    return parse_qs(urlparse(loc).query)["token"][0]


def test_google_auth_url_requires_config(client):
    res = client.get("/api/auth/google/url")
    assert res.status_code == 500
    assert "GOOGLE_CLIENT_ID" in res.json()["detail"]


def test_google_auth_url_returns_url(client, google_env):
    res = client.get("/api/auth/google/url")
    assert res.status_code == 200
    url = res.json()["url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-client-id" in url


def test_google_callback_issues_token(client, google_env, fake_google):
    # Get a real state first so the callback can consume it.
    res = client.get("/api/auth/google/url")
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]

    cb = client.get("/api/auth/google/callback", params={"code": "auth-code", "state": state},
                    follow_redirects=False)
    assert cb.status_code in (302, 307)
    assert cb.headers["location"].startswith("http://localhost:5173/?token=")

    token = _token_from_redirect(cb)
    me = client.get("/api/auth/me", headers=_auth_headers(token))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "user@example.com"
    assert me.json()["user"]["display_name"] == "Test User"


def test_google_callback_state_is_single_use(client, google_env, fake_google):
    res = client.get("/api/auth/google/url")
    state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]

    first = client.get("/api/auth/google/callback", params={"code": "c", "state": state},
                       follow_redirects=False)
    assert first.status_code in (302, 307)

    second = client.get("/api/auth/google/callback", params={"code": "c", "state": state},
                        follow_redirects=False)
    assert second.status_code == 400


def test_google_callback_bad_state(client, google_env, fake_google):
    cb = client.get("/api/auth/google/callback", params={"code": "c", "state": "nope"},
                    follow_redirects=False)
    assert cb.status_code == 400


def test_google_callback_reuses_existing_user(client, google_env, fake_google):
    for _ in range(2):
        res = client.get("/api/auth/google/url")
        state = parse_qs(urlparse(res.json()["url"]).query)["state"][0]
        cb = client.get("/api/auth/google/callback", params={"code": "c", "state": state},
                        follow_redirects=False)
        assert cb.status_code in (302, 307)
        _token_from_redirect(cb)

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


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_guest_gets_practice_mode(client):
    res = client.post("/api/start", json={"candidate_name": "anon"})
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "practice"
    assert data["candidate"].startswith("guest-")
    assert data["first_task"] is not None


def test_guest_can_start_practice(client):
    res = client.post("/api/start", json={"candidate_name": "anon"})
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "practice"
    assert data["candidate"].startswith("guest-")
    assert data["first_task"] is not None


def test_guest_practice_submit_is_unscored(client, fake_judge):
    started = client.post("/api/start", json={"candidate_name": "anon"})
    sid = started.json()["session_id"]
    task_id = started.json()["first_task"]["id"]

    res = client.post("/api/submit", json={"session_id": sid, "task_id": task_id, "answer": "def f(): pass"})
    assert res.status_code == 200
    data = res.json()
    assert data["feedback"] == "Great job!"
    assert data["skill_update"] is None


def test_authenticated_start_uses_account(client, google_env):
    user = auth.upsert_google_user("alice@b.co", "Alice")
    token = auth.create_token(user["id"])

    res = client.post(
        "/api/start",
        json={"candidate_name": "whatever"},
        headers=_auth_headers(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "assessment"
    assert data["candidate"] == "alice@b.co"


def test_sessions_are_scoped_to_account(client, google_env):
    user = auth.upsert_google_user("bob@b.co", "Bob")
    token = auth.create_token(user["id"])
    client.post(
        "/api/start",
        json={"candidate_name": "bob"},
        headers=_auth_headers(token),
    )

    mine = client.get("/api/sessions", headers=_auth_headers(token))
    assert mine.status_code == 200
    assert len(mine.json()["sessions"]) == 1

    guest = client.get("/api/sessions")
    assert guest.status_code == 200
    assert guest.json()["sessions"] == []


def test_guest_cannot_open_named_session(client, google_env):
    user = auth.upsert_google_user("carol@b.co", "Carol")
    token = auth.create_token(user["id"])
    started = client.post(
        "/api/start",
        json={"candidate_name": "carol"},
        headers=_auth_headers(token),
    )
    sid = started.json()["session_id"]

    guest_open = client.post("/api/session/open", json={"id": sid, "status": "active"})
    assert guest_open.status_code == 403
    assert "practice" in guest_open.json()["detail"]


def test_guest_can_reopen_own_practice_session(client):
    started = client.post("/api/start", json={"candidate_name": "anon"})
    sid = started.json()["session_id"]

    reopen = client.post("/api/session/open", json={"id": sid, "status": "active"})
    assert reopen.status_code == 200
    assert reopen.json()["mode"] == "practice"
    assert reopen.json()["candidate"].startswith("guest-")