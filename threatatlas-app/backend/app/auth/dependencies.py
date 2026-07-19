"""FastAPI dependencies for authentication."""

import hashlib
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth.jwt import decode_access_token
from app.database import get_db
from app.models import User

# HTTP Bearer token security scheme
security = HTTPBearer()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExpiredApiToken(Exception):
    """Raised by resolve_user_from_bearer when a ta_ API token has expired."""


def resolve_user_from_bearer(raw: str, db: Session) -> User | None:
    """
    Resolve a User from a raw bearer token (JWT or long-lived ta_ API token).

    Returns None if the token is missing/invalid/inactive-user. Raises
    ExpiredApiToken if it's a recognized but expired ta_ token, so callers can
    surface a more specific message than the generic "invalid credentials".
    """
    # ── Try JWT first ──────────────────────────────────────────────────────
    try:
        payload = decode_access_token(raw)
        user_id = payload.get("sub")
        if user_id is None:
            return None
        user_id = int(user_id)
        user = db.query(User).filter(User.id == user_id).first()
        if user is None or not user.is_active:
            return None
        return user
    except (JWTError, ValueError):
        pass

    # ── Fall back to API token (ta_ prefix) ────────────────────────────────
    if raw.startswith("ta_"):
        from app.models.api_token import ApiToken
        token_row = db.query(ApiToken).filter(ApiToken.token_hash == _hash_token(raw)).first()
        if token_row is None:
            return None
        # Honour expiry
        if token_row.expires_at and token_row.expires_at < datetime.now(timezone.utc):
            raise ExpiredApiToken()
        user = db.query(User).filter(User.id == token_row.user_id).first()
        if user is None or not user.is_active:
            return None
        # Stamp last use (best-effort, don't fail the request on error)
        try:
            token_row.last_used_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        return user

    return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Authenticate via JWT or long-lived API token (ta_ prefix)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user = resolve_user_from_bearer(credentials.credentials, db)
    except ExpiredApiToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get the current active user (convenience dependency).

    Args:
        current_user: The current user from get_current_user

    Returns:
        The authenticated active User object

    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user
