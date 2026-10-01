import os
import sys
from urllib.parse import urlencode, urlsplit

from fastapi import Request, HTTPException
from fastapi.responses import Response, RedirectResponse, JSONResponse
from app.api.deps import get_current_user
from app.core.auth_cache import (
    cache_admin_exists,
    cache_user,
    get_cached_admin_exists,
    get_cached_user,
)
from app.core.logging import setup_logger
from app.core.navigation import safe_local_return_to
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.crud.user import is_admin_user_exists, get_user_by_email
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
logger = setup_logger(__name__)


def _redirect_to_login(request: Request, *, clear_cookie: bool = False) -> Response:
    if request.url.path.startswith("/api/"):
        response = JSONResponse({"detail": "Sign in required"}, status_code=401)
        if clear_cookie:
            response.delete_cookie("access_token")
        return response
    return_to = safe_local_return_to(
        f"{request.url.path}{'?' + request.url.query if request.url.query else ''}"
    )
    response = RedirectResponse(
        url=f"/login.html?{urlencode({'next': return_to})}", status_code=303
    )
    if clear_cookie:
        response.delete_cookie("access_token")
    return response


def _cross_origin_browser_write(request: Request) -> bool:
    """Reject cross-origin browser mutations using ambient login credentials."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return False
    if request.url.path not in {"/login", "/setup"} and (
        not request.cookies.get("access_token") or request.headers.get("authorization")
    ):
        return False
    source = request.headers.get("origin") or request.headers.get("referer")
    if source:
        try:
            origin = urlsplit(source)
            target = urlsplit(str(request.url))
            return (
                origin.scheme,
                origin.hostname,
                origin.port or (443 if origin.scheme == "https" else 80),
            ) != (
                target.scheme,
                target.hostname,
                target.port or (443 if target.scheme == "https" else 80),
            )
        except ValueError:
            return True
    return request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}


async def auth_middleware(request: Request, call_next) -> Response:
    """Apply browser protections even to auth redirects and failed logins."""
    if _cross_origin_browser_write(request):
        response = Response("Cross-origin request denied", status_code=403)
    else:
        response = await _authenticate_request(request, call_next)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if (
        request.cookies.get("access_token")
        or request.headers.get("authorization")
        or (
            request.url.path
            in {"/login", "/login.html", "/logout", "/setup", "/setup.html"}
            or request.url.path.startswith("/auth/")
            or "set-cookie" in response.headers
        )
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


async def _authenticate_request(request: Request, call_next):
    if "pytest" in sys.modules and os.environ.get(
        "ENABLE_AUTH_MIDDLEWARE_IN_TESTS", ""
    ).lower() not in {"1", "true", "yes"}:
        return await call_next(request)
    token = request.cookies.get("access_token", None)

    path = request.url.path

    # Static assets and health checks should never hit auth/setup gating.
    if path.startswith("/static/") or path in {"/favicon.ico", "/health"}:
        return await call_next(request)
    # Avoid per-request auth logs; they overwhelm operator logs.
    # We log only redirects or auth failures below.

    if path not in ("/setup.html", "/setup", "/login.html", "/login", "/favicon.ico"):
        admin_exists = get_cached_admin_exists()
        if admin_exists is None:
            db = SessionLocal()
            try:
                admin_exists = cache_admin_exists(is_admin_user_exists(db))
            finally:
                db.close()
        if not admin_exists:
            logger.debug("Auth redirect: no admin user; setup required")
            return RedirectResponse(url="/setup.html", status_code=303)

    if token is None:
        if (
            path.endswith(".html") or path in ("/", "/index.html", "/bridge")
        ) and path not in (
            "/login.html",
            "/setup.html",
        ):
            logger.debug("Auth redirect: missing token; login required")
            return _redirect_to_login(request)
    elif (
        request.url.path in ("/login.html", "/login", "/setup.html")
        and request.method == "GET"
    ):
        # If the user already has a valid token, redirect them away from the
        # login page. Otherwise allow the request to continue so the login form
        # is shown.
        if token is not None:
            try:
                email = decode_access_token(token)
                if not email:
                    raise HTTPException(status_code=401, detail="Invalid token")
                user = get_cached_user(email)
                if user is None:
                    db = SessionLocal()
                    try:
                        user = get_user_by_email(db, email=email)
                        if user:
                            user = cache_user(user)
                    finally:
                        db.close()
                if user:
                    return RedirectResponse(
                        url=safe_local_return_to(request.query_params.get("next")),
                        status_code=303,
                    )
            except HTTPException:
                # Invalid token should not prevent access to the login page
                pass
    elif request.url.path not in ("/favicon.ico", "/login"):
        try:
            email = decode_access_token(token)
            if not email:
                raise HTTPException(status_code=401, detail="Invalid token")
            user = get_cached_user(email)
            if user is None:
                db = SessionLocal()
                try:
                    user = get_user_by_email(db, email=email)
                    if user:
                        user = cache_user(user)
                finally:
                    db.close()
            if not user:
                raise HTTPException(status_code=401, detail="Invalid token")
        except HTTPException as e:
            if e.status_code == 401:
                logger.debug("Auth redirect: invalid token; login required")
                return _redirect_to_login(request, clear_cookie=True)
            raise e

    response = await call_next(request)
    return response
