from hmac import compare_digest

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import User
from app.core.auth_cache import get_cached_user, cache_user
from app.core.security import decode_access_token
from app.crud.user import get_user_by_email

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token", auto_error=False)


def get_db():
    """Provide a synchronous database session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """Provide an asynchronous database session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)):
    """Return the current authenticated user.

    Args:
        token: OAuth2 access token extracted from the request.

    Returns:
        The user associated with the token.

    Raises:
        HTTPException: If authentication fails or user does not exist.
    """

    if not token:
        token = request.cookies.get("access_token")
    email = decode_access_token(token) if token else None
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    cached_user = get_cached_user(email)
    if cached_user is not None:
        return cached_user
    async for db in get_async_db():
        user = get_user_by_email(db, email=email)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return cache_user(user)


def _bearer_token_value(token: str | None) -> str:
    return str(token or "").strip().split(" ")[-1]


def _cached_or_db_user_for_service_token(
    db: Session,
    *,
    email: str,
    missing_detail: str,
) -> User:
    cached_user = get_cached_user(email)
    if cached_user is not None:
        return cached_user
    user = get_user_by_email(db, email=email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=missing_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return cache_user(user)


async def get_console_runtime_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Authenticate console runtime traffic.

    Runtime API clients can use regular Norman user JWTs. Internal TUI bridge
    workers can also use a narrow service token that maps to one configured
    Norman user, keeping durable runtime jobs/events in the existing user scope.
    """

    configured_token = str(settings.console_runtime_service_token or "").strip()
    candidate = _bearer_token_value(token)
    if configured_token and candidate and compare_digest(candidate, configured_token):
        email = (
            str(settings.console_runtime_service_user_email or "").strip()
            or str(settings.initial_admin_email or "").strip()
        )
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Console runtime service user is not configured",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return _cached_or_db_user_for_service_token(
            db,
            email=email,
            missing_detail="Console runtime service user was not found",
        )

    return await get_current_user(request, token)


async def get_keys_service_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Authenticate Norman Keys compatibility clients.

    The compatibility endpoint is for broker clients such as NetOps/Uplink.
    During migration it accepts the existing console-runtime service token as
    well as a dedicated Norman Keys token, but it does not fall back to a
    regular user JWT. Interactive users should use the `/api/v1/keys/*` API.
    """

    candidate = _bearer_token_value(token)
    configured_tokens = [
        str(settings.norman_keys_service_token or "").strip(),
        str(settings.console_runtime_service_token or "").strip(),
    ]
    if candidate and any(
        configured and compare_digest(candidate, configured)
        for configured in configured_tokens
    ):
        email = (
            str(settings.norman_keys_service_user_email or "").strip()
            or str(settings.console_runtime_service_user_email or "").strip()
            or str(settings.initial_admin_email or "").strip()
        )
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Norman Keys service user is not configured",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return _cached_or_db_user_for_service_token(
            db,
            email=email,
            missing_detail="Norman Keys service user was not found",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate Norman Keys service credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
