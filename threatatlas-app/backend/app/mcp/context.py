"""Per-request actor propagation for MCP tool bodies.

FastMCP dispatches each tool call on the event loop with no request object
passed to the tool function. The authenticated user comes from the mcp SDK's
own auth contextvar (set by AuthContextMiddleware once
ThreatAtlasOAuthProvider.load_access_token resolves the bearer token); the
per-request DB session is ours to manage since the SDK has no concept of "a
SQLAlchemy session for this request" — McpDbSessionMiddleware (see
app/mcp/db_session_middleware.py) sets/resets it here.
"""

from contextvars import ContextVar, Token
from typing import NamedTuple

from mcp.server.auth.middleware.auth_context import get_access_token
from sqlalchemy.orm import Session

from app.models import User


class McpActor(NamedTuple):
    user: User
    db: Session


_db: ContextVar[Session] = ContextVar("mcp_db_session")


def set_mcp_db_session(db: Session) -> Token:
    """Set the DB session for this request and return a token for reset_mcp_db_session()."""
    return _db.set(db)


def reset_mcp_db_session(token: Token) -> None:
    _db.reset(token)


def get_mcp_db_session() -> Session:
    """Return the per-request DB session opened by McpDbSessionMiddleware.

    Used by ThreatAtlasOAuthProvider, whose Protocol methods are called
    directly by the SDK's Starlette routes (/authorize, /token, /register,
    /revoke) rather than through FastAPI's Depends() — but those routes all
    live on the same mcp.streamable_http_app() that McpDbSessionMiddleware
    wraps (see app/mcp/server.py), so the session is already set by the time
    any of these methods run.
    """
    return _db.get()


def get_mcp_actor() -> McpActor:
    """Return the (user, db) for the in-flight, already-authenticated MCP call.

    Raises LookupError if called outside an authenticated MCP request, or if
    the access token's subject no longer maps to an active user — both would
    be bugs in the auth wiring, not a normal error path.
    """
    access_token = get_access_token()
    if access_token is None or access_token.subject is None:
        raise LookupError("no authenticated MCP actor for this request")

    db = _db.get()
    user = db.query(User).filter(User.id == int(access_token.subject)).first()
    if user is None or not user.is_active:
        raise LookupError("MCP access token subject does not map to an active user")
    return McpActor(user=user, db=db)
