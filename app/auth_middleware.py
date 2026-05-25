import os
import sys
from fastapi import Request, HTTPException
from fastapi.responses import Response, RedirectResponse
from app.api.deps import get_current_user
from app.core.auth_cache import (
    cache_admin_exists,
    cache_user,
    get_cached_admin_exists,
    get_cached_user,
)
from app.core.logging import setup_logger
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.crud.user import is_admin_user_exists, get_user_by_email
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
logger = setup_logger(__name__)


async def auth_middleware(request: Request, call_next):
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
        if (path.endswith(".html") or path in ("/", "/index.html")) and path not in (
            "/login.html",
            "/setup.html",
        ):
            logger.debug("Auth redirect: missing token; login required")
            return RedirectResponse(url="/login.html", status_code=303)
    elif request.url.path in ("/login.html", "/setup.html"):
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
                    return RedirectResponse(url="/index.html", status_code=303)
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
                # return Response(content="Unauthorized", status_code=401)
                logger.debug("Auth redirect: already authenticated")
                return RedirectResponse(url="/index.html", status_code=303)
            raise e

    response = await call_next(request)
    return response
