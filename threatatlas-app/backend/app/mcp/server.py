"""Builds the ThreatAtlas MCP server and exposes it as a mountable ASGI app.

FastMCP's streamable_http_app() returns a single Starlette app whose routes
include the actual /mcp endpoint *and* the OAuth 2.1 routes (/authorize,
/token, /register, /revoke, /.well-known/oauth-authorization-server,
/.well-known/oauth-protected-resource/mcp) as siblings — see
app/main.py for why this whole sub-app must be mounted at the FastAPI root,
as the very last route, rather than under an "/mcp" prefix.

Bearer-token verification (including the legacy ta_/JWT static-token
fallback) is handled by ThreatAtlasOAuthProvider.load_access_token, wired in
via auth_server_provider below — FastMCP derives its own BearerAuthBackend
from it. "One DB session per tool call" is not something the SDK's auth
stack provides, so McpDbSessionMiddleware still wraps the app for that.
"""

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.config import settings
from app.mcp.db_session_middleware import McpDbSessionMiddleware
from app.mcp.oauth_provider import ThreatAtlasOAuthProvider

mcp = FastMCP(
    name="threatatlas",
    # Trailing slash matches what MCP clients (and our own tests) POST to —
    # this is registered as an exact-match Route, not a Mount, so a mismatch
    # here would 307-redirect and break clients that don't follow redirects
    # on POST.
    streamable_http_path="/mcp/",
    stateless_http=True,
    json_response=True,
    auth_server_provider=ThreatAtlasOAuthProvider(),
    auth=AuthSettings(
        issuer_url=settings.backend_base_url,
        resource_server_url=f"{settings.backend_base_url}/mcp",
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    ),
    # FastMCP's default DNS-rebinding protection only allow-lists Host headers
    # of 127.0.0.1/localhost, which rejects every request in a real deployment
    # (proxied domain, docker service name, TestClient's "testserver", ...).
    # That protection exists for MCP servers with no auth of their own; every
    # /mcp request here is already gated by the OAuth bearer-token check
    # above, which a malicious page cannot forge, so it's safe to disable.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

import app.mcp.tools  # noqa: E402,F401  (registers @mcp.tool() functions)

mcp_asgi_app = McpDbSessionMiddleware(mcp.streamable_http_app())
