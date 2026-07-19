"""ASGI middleware that opens a per-request DB session for Streamable HTTP
MCP requests.

Bearer-token verification is handled upstream by FastMCP's own auth stack
(BearerAuthBackend + ThreatAtlasOAuthProvider.load_access_token) before this
middleware runs — see app/mcp/server.py. All this does is give tool bodies a
SQLAlchemy session for the duration of the request, obtained through
scope["app"].dependency_overrides (falling back to the real get_db) so tests
overriding get_db see MCP tool calls hit the same session as the rest of the
test.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from app.database import get_db
from app.mcp.context import reset_mcp_db_session, set_mcp_db_session


class McpDbSessionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        root_app = scope["app"]
        db_factory = root_app.dependency_overrides.get(get_db, get_db)
        db_gen = db_factory()
        db = next(db_gen)
        try:
            db_token = set_mcp_db_session(db)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_mcp_db_session(db_token)
        finally:
            next(db_gen, None)
