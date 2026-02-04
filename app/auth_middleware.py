from fastapi import Request, HTTPException
from fastapi.responses import Response, RedirectResponse
from app.api.deps import get_current_user
from app.core.logging import setup_logger
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.crud.user import is_admin_user_exists, get_user_by_email
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
logger = setup_logger(__name__)


async def auth_middleware(request: Request, call_next):
    token = request.cookies.get("access_token", None)

    path = request.url.path
    logger.info(
        "Auth middleware: path=%s token=%s", path, "present" if token else "missing"
    )

    if path not in ("/setup.html", "/setup", "/login.html", "/login", "/favicon.ico"):
        db = SessionLocal()
        try:
            if not is_admin_user_exists(db):
                return RedirectResponse(url="/setup.html", status_code=303)
        finally:
            db.close()

    if token is None:
        if (path.endswith(".html") or path in ("/", "/index.html")) and path not in (
            "/login.html",
            "/setup.html",
        ):
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
                db = SessionLocal()
                try:
                    user = get_user_by_email(db, email=email)
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
            db = SessionLocal()
            try:
                user = get_user_by_email(db, email=email)
            finally:
                db.close()
            if not user:
                raise HTTPException(status_code=401, detail="Invalid token")
        except HTTPException as e:
            if e.status_code == 401:
                # return Response(content="Unauthorized", status_code=401)
                return RedirectResponse(url="/login.html", status_code=303)
            raise e

    response = await call_next(request)
    return response
