"""CSRF protection for cookie-authenticated state-changing requests.

Cookies (``SameSite=Lax``) already block most cross-site writes, but a
top-level navigation or a same-site bypass could still ride the session
cookie. This middleware additionally requires a matching ``Origin`` (or
``Referer``) header whenever ALL of these hold:

- the method is unsafe (POST / PATCH / PUT / DELETE),
- no ``Authorization: Bearer`` header is present (Bearer callers opt out of
  cookies: :func:`backend.auth.get_current_user` ignores the cookie when a
  Bearer header is sent, so there is nothing to forge),
- the session cookie is present.

Browser ``fetch`` always sends ``Origin`` on such requests; non-browser API
clients should send ``Origin`` too (or use a Bearer token instead).
Safe methods (GET / HEAD / OPTIONS) are never checked.
"""

import os
from urllib.parse import urlparse

from starlette.responses import JSONResponse

from backend.auth import AUTH_COOKIE_NAME

UNSAFE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _allowed_netlocs() -> set[str]:
    """Host[:port] values accepted as request origins (per-request env read)."""
    netlocs = {"localhost:5173", "localhost:3000", "127.0.0.1:5173", "127.0.0.1:3000"}
    for raw in [os.getenv("FRONTEND_URL", ""), *os.getenv("CORS_ORIGINS", "").split(",")]:
        raw = raw.strip().rstrip("/")
        if raw:
            netlocs.add(urlparse(raw).netloc.lower())
    return {n for n in netlocs if n}


def origin_allowed(request, origin_or_referer: str | None) -> bool:
    """True when the origin matches this host or a configured frontend origin."""
    if not origin_or_referer:
        return False
    netloc = urlparse(origin_or_referer).netloc.lower()
    if not netloc or netloc == "null":
        return False
    if netloc == request.url.netloc.lower():
        return True
    return netloc in _allowed_netlocs()


async def csrf_protect(request, call_next):
    """Starlette HTTP middleware enforcing the rule above (403 on failure)."""
    auth = request.headers.get("authorization", "")
    if (
        request.method in UNSAFE_METHODS
        and not auth.startswith("Bearer ")
        and AUTH_COOKIE_NAME in request.cookies
    ):
        origin = request.headers.get("origin") or request.headers.get("referer")
        if not origin_allowed(request, origin):
            return JSONResponse(
                {"detail": "CSRF check failed: send a matching Origin header."},
                status_code=403,
            )
    return await call_next(request)
