"""Authentication routes (Google OAuth + bearer identity).

Auth stays at ``/api/auth/*`` in Phase 2 (the OAuth redirect URI is
registered externally); the Phase 3 cookie cutover moves it without
changing these paths.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from backend import google_auth
from backend.auth import (
    AUTH_COOKIE_NAME,
    create_token,
    require_user,
    revoke_token,
    upsert_google_user,
)

router = APIRouter(prefix="/api")


@router.get("/auth/google/url", tags=["auth"], summary="Get Google OAuth URL")
def google_auth_url():
    """Return the Google authorization URL for the frontend to redirect to."""
    try:
        url, _ = google_auth.new_authorization_url()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"url": url}


@router.get("/auth/google/callback", tags=["auth"], summary="Google OAuth callback")
def google_auth_callback(code: str, state: str, response: Response):
    """OAuth callback: verify state, exchange code, upsert user, redirect with token.

    Sets the ``ai_coach_token`` HttpOnly cookie in addition to the legacy
    ``?token=`` redirect query param (removed in Phase 3).
    """
    if not google_auth.consume_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")
    try:
        tokens = google_auth.exchange_code(code)
        info = google_auth.fetch_userinfo(tokens["access_token"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    email = (info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email.")
    user = upsert_google_user(email, info.get("name") or "")
    token = create_token(user["id"])
    redirect = RedirectResponse(url=f"{google_auth.frontend_url()}/?token={quote(token)}")
    redirect.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=google_auth.frontend_url().startswith("https://"),
        path="/",
        max_age=30 * 24 * 3600,
    )
    return redirect


@router.post("/auth/logout", tags=["auth"], summary="Revoke bearer token")
def logout(request: Request, response: Response):
    auth = request.headers.get("Authorization", "")
    token = None
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):].strip()
    if not token:
        token = request.cookies.get(AUTH_COOKIE_NAME, "")
    if token:
        revoke_token(token.strip())
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", tags=["auth"], summary="Current user")
def me(user: dict = Depends(require_user)):
    return {"user": user}
